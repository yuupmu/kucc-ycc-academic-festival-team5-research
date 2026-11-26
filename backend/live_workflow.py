import ast
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime

from .adapters import agent_input
from . import allocation_repair, allocation_dispatch, allocation_evidence
from .isolated import check_code
from .decision_checks import answer_cases, context_only, update_verification
from .live_schemas import (PLAN, MAIN_QUESTIONS, REQUESTS, obj, schemas_for, main_rules, monitor_rules,
                           ALLOCATION_PATCH, ALLOCATION_PATCH_RULES, ALLOCATION_READBACK, ALLOCATION_READBACK_RULES)
from .tasks import TASKS, task_id
from .diagnostics import timestamp, safe_log, validate_monitor, validate_requests, error_record, ResponseValidationError


class RunStopped(Exception):
    pass


class LiveWorkflow:
    MAX_AUTONOMOUS_STEPS = 6
    MAX_REPORT_RETRIES = 2

    def _public_verification(self, code, checks, selected_task):
        # Candidate mistakes become feedback for revision, not fatal workflow errors.
        try:
            definition = TASKS[selected_task]
            tree = ast.parse(code)
            if not any(isinstance(n, ast.FunctionDef) and n.name == definition['function'] and len(n.args.args) == len(definition['arguments']) for n in tree.body):
                raise ValueError('%s(%s) 함수가 필요합니다.' % (definition['function'], ', '.join(definition['arguments'])))
            if selected_task == 'allocation':
                return check_code(code, checks, selected_task, proposals=True)
            return check_code(code, checks, selected_task)
        except (SyntaxError, ValueError, RuntimeError) as exc:
            message = ('Python 문법 오류 (줄 %s)' % exc.lineno) if isinstance(exc, SyntaxError) else str(exc)[:1000]
            return {'passed': False, 'correct': 0, 'total': len(checks) if isinstance(checks, list) else 0,
                    'results': [], 'error': message}

    def _record_call_error(self, state, call, exc, ignored=False):
        if call and call.get('error'):
            return
        if call:
            if getattr(exc, 'response', None) is not None:
                call['raw_response'] = safe_log(exc.response)
                call['response_id'] = exc.response.get('id')
                call['stage'] = 'response_decoding'
            self._finish_call(call)
        record = error_record(exc, call, state['phase'], state['code_version'], state.get('execution_epoch', 0))
        record['ignored'] = ignored
        if call:
            record['execution_epoch'] = call.get('execution_epoch', record['execution_epoch'])
            record['code_version'] = call.get('input', {}).get('project_state', {}).get('code_version', record['code_version'])
        state.setdefault('diagnostics', []).append(record)
        if call:
            call.update(status='failed', error=record)

    def _verify_revision(self, code, checks, task, decisions):
        if task == 'allocation' and checks == []:
            capacities = dict(seats=0, laptops=0, projectors=0)
            check_input = {'initial_state': {'capacities': capacities}, 'events': []}
            final_state = dict(capacities=capacities, available=capacities, reservations=[], waitlist=[])
            checks = [{'input_json': json.dumps(check_input), 'expected_json': json.dumps(
                dict(event_results=[], final_state=final_state, notifications=[]))}]
        result = self._public_verification(code, checks, task)
        result['decision_status'] = {}
        result['needs_examples'] = []
        if task == 'cancellation_basic':
            for decision in decisions:
                key = decision['request_id']
                text = decision['answer']['text']
                examples = answer_cases(text)
                if not examples:
                    if not context_only(text):
                        result['needs_examples'].append(key)
                    continue
                checked = self._public_verification(code, examples, task)
                result['decision_status'][key] = checked['passed']
                for row in checked['results']:
                    result['results'].append(dict(row, request_id=key))
                result['total'] += checked['total']
                result['correct'] += checked['correct']
                if checked.get('error'):
                    result['error'] = checked['error']
        update_verification(result)
        return result

    def _finish_call(self, call):
        call['finished_at'] = timestamp()
        if call.get('started_at'):
            call['elapsed_ms'] = round((datetime.fromisoformat(call['finished_at']) - datetime.fromisoformat(call['started_at'])).total_seconds() * 1000)

    def _capture_response(self, state, call, result, metadata, epoch):
        # Persist before validation, including responses arriving after a pause.
        call.update(output=safe_log(result), **safe_log(metadata))
        call['response_received_at'] = timestamp()
        call['stage'] = 'response_validation'
        self._finish_call(call)
        if not self._live_active(state, epoch):
            call['status'] = 'discarded'
        self._save(state)

    def _pause_live_error(self, state, message):
        message = safe_log(message)
        state.update(status='paused', phase='오류 · 답변 입력/계속하기 대기',
                     pause_reason='execution_error', last_error=message)
        self._event(state, message)
        self._save(state)

    def _live_active(self, state, epoch):
        return state['status'] in self.ACTIVE and state.get('execution_epoch', 0) == epoch

    def _live_context(self, state, *, for_writer=False):
        context = self._context(state)
        benchmark = self._benchmark_path(state)
        public_task = (benchmark / TASKS[task_id(state)].get('brief', 'agent/TASK.md')).read_text()
        if task_id(state) == 'allocation':
            public_task += '\n' + (benchmark / 'agent/OUTPUT_FORMAT.md').read_text()
        context.update(task=public_task,
                       assumptions=state.get('assumptions', []), requests=state['requests'],
                       monitor_feedback=state['monitors'], verification=state['verification'],
                       last_error=state.get('last_error'), rejected_code=state.get('rejected_code'),
                       required_decision_ids=[d['request_id'] for d in state['decisions']],
                       response_feedback=state.get('response_feedback'))
        answered = {r['id'] for r in state['requests'] if r['status'] in ('answered', 'check_failed', 'needs_example')}
        context['pending_reviews'] = [r for r in state.get('review_log', [])
                                      if r.get('delivered_version') is None or answered.intersection(r.get('request_ids', []))]
        if task_id(state) == 'allocation':
            context['scheduling_decisions'] = allocation_repair.review_packet(state)
            draft = state.get('scheduling_draft') if for_writer else None
            if draft and draft['base_version'] == state['code_version']:
                context['code'] = draft['code']
                context['accepted_in_draft'] = {
                    d['request_id']:draft['accepted'][d['request_id']]['status']
                    for d in state['decisions'] if d['request_id'] in draft['accepted']
                    and draft['accepted'][d['request_id']]['answer'] == [d['answer'],d.get('note','')]}
                context['rejected_code'] = None
            context['schedule_patch_required'] = bool(context['code'] and context['decisions'] and (
                state.get('scheduling_initialized') or any(r.get('applied_version') for r in state['requests'])
                or not allocation_repair.empty_scaffold(context['code'])))
            active = {r['id'] for r in state['requests'] if r['status'] == 'answered'}
            for review in context['pending_reviews']:
                active.update(review.get('affected_decision_ids', []))
                active.update(review.get('request_ids', []))
            active.difference_update(context.get('accepted_in_draft', {}))
            active.update((state.get('response_feedback') or {}).get('repair_ids', []))
            context['editable_decision_ids'] = sorted(active.intersection(context['required_decision_ids']))
            context['pending_code_sites'] = allocation_repair.pending_sites(context['code'])
            context['event_completions'] = {key:{k:v for k,v in option.items() if k!='after'}
                                            for key,option in allocation_dispatch.capacity_options(context).items()}
            context['verification'] = None
            context['last_error'] = None
            context['monitor_feedback'] = [{k:v for k,v in m.items() if k != 'verification'}
                                           for m in context['monitor_feedback']]
            context['pending_reviews'] = [{k:v for k,v in r.items() if k not in ('checks','verification')}
                                          for r in context['pending_reviews']]
        return context

    def _schedule_readback(self, run_id, epoch, task, candidate, version, decision):
        key = decision['request_id']
        evidence = [candidate,task,decision['question'],decision['answer'],decision.get('note',''),decision.get('reviews',[])]
        signature = hashlib.sha256(json.dumps(evidence,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        with self.cv:
            previous = self._state(run_id).get('scheduling_confirmations',{}).get(key)
            if previous and previous['signature']==signature:
                return previous['row']
        fields = ALLOCATION_READBACK['properties']['decisions']['items']['properties']
        schema = obj({'decisions':{'type':'array','items':obj({**fields,'request_id':{'type':'string','enum':[key]}})}})
        view = dict(task=task,code=candidate,code_version=version,scheduling_decisions=[decision])
        for pass_number in range(2):
            observed, _ = self._live_call(run_id,'inspect_schedule_patch',schema,epoch,readback=view)
            items = observed.get('decisions')
            if not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],dict) or items[0].get('request_id')!=key:
                raise ValueError('요청한 담당자 답변 한 건을 후보 코드와 대조해야 합니다.')
            row = items[0]
            if row.get('status')=='context' or (row.get('status')=='implemented' and
                                                allocation_repair.has_code_evidence(candidate,row.get('code_excerpt'))):
                break
            if not pass_number:
                view=dict(view,first_reading=row,source_path=allocation_repair.review_path(candidate,row.get('code_excerpt')))
                continue
            cases = allocation_evidence.panel(task,decision,row) if row.get('status') in ('unresolved','mismatch') else []
            if cases:
                witness_schema, questions = allocation_evidence.form(cases)
                policy, _ = self._live_call(run_id,'interpret_schedule_policy',witness_schema,epoch,
                    readback=dict(task=task,owner_question=decision['question'],owner_answer=decision['answer']['text'],
                                  owner_note=decision.get('note',''),dispute=row.get('reason',''),observations=questions))
                if policy.get('covers_dispute') is True and allocation_evidence.confirm(candidate,cases,policy.get('predictions')):
                    row=dict(row,status='implemented',owner_checks=len(cases),
                             reason='담당자 원문에서 도출한 관찰값을 이 후보 코드에서 확인했습니다.')
        if row.get('status') == 'context' or (row.get('status') == 'implemented' and
                (row.get('owner_checks') or allocation_repair.has_code_evidence(candidate,row.get('code_excerpt')))):
            with self.cv:
                state=self._state(run_id)
                if not self._live_active(state,epoch):
                    raise RunStopped()
                state.setdefault('scheduling_confirmations',{})[key]=dict(signature=signature,row=row,
                    code_sha256=hashlib.sha256(candidate.encode()).hexdigest())
        return row

    @staticmethod
    def _reviewed_schedule_repair(state, envelope, result):
        """The writer predicts completion before applying an edit. All observers judge the actual revision."""
        before=envelope['project_state']
        if (not before.get('schedule_patch_required') or not before.get('pending_code_sites') or not result.get('edits')
                or result.get('requests') or not state['monitors'] or allocation_repair.pending_sites(state['artifact']['code'])):
            return False
        digest=state['artifact']['sha256']
        receipts={d['request_id'] for d in state['decisions']}
        confirmed=state.get('scheduling_confirmations',{})
        if (not receipts or any(confirmed.get(k,{}).get('code_sha256')!=digest for k in receipts)
                or any(r['status'] not in ('applied','acknowledged') for r in state['requests'])):
            return False
        if not all(m['status']=='observed' and m['version']==state['code_version'] and m['decision']=='continue'
                   for m in state['monitors']):
            return False
        # Pure acknowledgements of the published code have nothing left for a writer to apply.
        return all(r.get('delivered_version') is not None or (
                   r.get('decision')=='continue' and not r.get('requests') and not r.get('affected_decision_ids'))
                   for r in state.get('review_log',[]))

    def _live_implement(self, run_id, selected_task, epoch):
        attempt = 0
        while True:
            result, envelope = self._live_call(run_id, 'implement', schemas_for(selected_task)[0], epoch)
            packet = envelope['project_state']
            expected = {d['request_id'] for d in packet['decisions']}
            reported = result.get('applied_decision_ids')
            context_ids = result.get('context_decision_ids', [])
            valid = all(isinstance(ids, list) and all(isinstance(x, str) for x in ids) for ids in [reported, context_ids])
            if valid and selected_task == 'allocation' and packet['schedule_patch_required']:
                reported, context_ids = list(reported), list(context_ids)
                for key, previous_status in allocation_repair.carried_decisions(packet).items():
                    if key not in reported and key not in context_ids:
                        (reported if previous_status == 'applied' else context_ids).append(key)
                result.update(applied_decision_ids=reported, context_decision_ids=context_ids)
            actual = set(reported) | set(context_ids) if valid else set()
            disjoint = (valid and len(reported) == len(set(reported)) and len(context_ids) == len(set(context_ids))
                        and not (set(reported) & set(context_ids)))
            schedule_error = None
            staged = None
            repair_ids = []
            clarifications = {}
            if selected_task == 'allocation' and expected and disjoint and actual == expected:
                try:
                    if packet['schedule_patch_required']:
                        edits = result.get('edits')
                        if isinstance(edits,list) and packet.get('event_completions'):
                            choices = allocation_dispatch.capacity_options(packet)
                            expanded = []
                            for edit in edits:
                                if not isinstance(edit,dict):
                                    raise ValueError('배정 편집 형식을 확인하세요.')
                                choice = choices.get(edit.get('after'))
                                if edit.get('after') == '@custom':
                                    raise ValueError('요청한 조건에 맞는 기존 처리 조합이 없어 직접 편집이 필요합니다.')
                                if choice:
                                    if (choice['request_id'],choice['before']) != (edit.get('request_id'),edit.get('before')):
                                        raise ValueError('이 답변에 연결된 배정 분기를 선택하세요.')
                                    edit=dict(edit,after=choice['after'])
                                    result['checks'] = [allocation_dispatch.capacity_check(choice['result'])]
                                expanded.append(edit)
                            edits=expanded
                        result['code'] = allocation_repair.apply_edits(packet['code'], edits,
                            packet['decisions'], set(packet['editable_decision_ids']) & set(reported))
                    candidate = result.get('code')
                    if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 100000:
                        raise ValueError('후보 코드가 비어 있거나 크기 제한을 넘었습니다.')
                    rows = [self._schedule_readback(run_id,epoch,packet['task'],candidate,packet['code_version'],decision)
                            for decision in packet['scheduling_decisions']]
                    if {row['request_id'] for row in rows} != expected:
                        raise ValueError('받은 담당자 답변 중 코드와 대조하지 않은 항목이 있습니다.')
                    reasons = []
                    for row in rows:
                        key, excerpt = row['request_id'], row.get('code_excerpt')
                        if row.get('status') == 'context' and key in context_ids:
                            continue
                        if (row.get('status') == 'implemented' and key in reported
                                and (row.get('owner_checks') or allocation_repair.has_code_evidence(candidate, excerpt))):
                            continue
                        if row.get('status') == 'unresolved':
                            clarifications[key] = str(row.get('reason') or '판단에 필요한 운영 조건을 알려주세요.')[:1200]
                        repair_ids.append(key)
                        reasons.append(str(row.get('reason',''))[:400])
                    if repair_ids:
                        accepted = {d['request_id']:dict(answer=[d['answer'],d.get('note','')],
                                    status='applied' if d['request_id'] in reported else 'acknowledged')
                                    for d in packet['decisions'] if d['request_id'] not in repair_ids}
                        staged = dict(base_version=packet['code_version'],code=candidate,accepted=accepted)
                        raise ValueError('담당자 원문과 실제 코드의 분기를 다시 맞추세요. ' + ' / '.join(reasons))
                except ValueError as exc:
                    schedule_error = str(exc)
            with self.cv:
                state = self._state(run_id)
                if not self._live_active(state, epoch):
                    raise RunStopped()
                if staged:
                    state['scheduling_draft']=staged
                if clarifications:
                    for req in state['requests']:
                        if req['id'] in clarifications:
                            req.update(status='needs_example', clarification=clarifications[req['id']])
                            req.pop('applied_version', None)
                    state.update(status='waiting', phase='배정 조건에 대한 담당자 답변 대기')
                    self._live_task_status(state)
                    self._save(state)
                    while self._live_active(state, epoch) and any(
                            r['id'] in clarifications and r['status']=='needs_example' for r in state['requests']):
                        self.cv.wait(timeout=1)
                    if not self._live_active(state, epoch):
                        raise RunStopped()
                    state.update(status='running', phase='코드 작성·수정')
                    attempt = 0
                    continue
                if disjoint and actual == expected and not schedule_error:
                    state.pop('response_feedback', None)
                    state.pop('rejected_code', None)
                    if attempt:
                        self._event(state, '답변 반영 보고 재요청 완료. 코드 검증을 진행합니다.')
                    self._save(state)
                    return result, envelope
                state['response_feedback'] = {
                    'error': '답변 처리 보고가 누락되거나 중복됐습니다. 코드 요구사항은 실제 반영 후 applied_decision_ids에, 코드 변경이 불필요한 맥락 답변은 context_decision_ids에 넣으세요. required_decision_ids의 각 ID를 정확히 한 목록에 포함하고 전체 소스를 다시 반환하세요. ID만 임의로 추가하지 마세요.',
                    'required_decision_ids': sorted(expected),
                    'missing_ids': sorted(expected - actual), 'unknown_ids': sorted(actual - expected),
                }
                if schedule_error:
                    state['response_feedback'].update(error=schedule_error, repair_ids=repair_ids)
                state['rejected_code'] = result.get('code')
                self._event(state, '답변 반영 보고 불일치 · 누락 %s건, 알 수 없는 ID %s건 · %s' %
                            (len(expected - actual), len(actual - expected),
                             '자동 재요청 %s/%s' % (attempt + 1, self.MAX_REPORT_RETRIES) if attempt < self.MAX_REPORT_RETRIES else '재요청 한도 도달'))
                self._save(state)
            if attempt == self.MAX_REPORT_RETRIES:
                if schedule_error:
                    raise ResponseValidationError('scheduling_decisions', sorted(expected), repair_ids, schedule_error)
                raise ResponseValidationError('decision_ids', sorted(expected), {'applied':reported,'context':context_ids}, '답변 반영 보고가 자동 재요청 2회 후에도 일치하지 않습니다. 답변은 보존됐으며, 계속하기로 재시도할 수 있습니다.')
            attempt += 1

    def _live_call(self, run_id, action, schema, epoch, *, readback=None):
        with self.cv:
            state = self._state(run_id)
            if not self._live_active(state, epoch):
                raise RunStopped()
            context = self._live_context(state,for_writer=action=='implement') if readback is None else readback
            envelope = agent_input('main', state['config']['mainAgent'], context, action)
            call = {'id':uuid.uuid4().hex, 'agent': 'main', 'input': envelope, 'status': 'running',
                    'started_at':timestamp(), 'stage':'api_request', 'execution_epoch':epoch}
            state['calls'].append(call)
            client = self.api_client
            self._save(state)
        instructions = main_rules(task_id(state))
        if readback is not None:
            instructions = ALLOCATION_READBACK_RULES
            if action=='interpret_schedule_policy':
                instructions = ('담당자의 원문을 읽고 각 가상 상황의 기대 동작을 선택한다. 코드와 실행 결과는 제공되지 않는다. '
                    '배열과 코드 문자열의 의미를 확인한다. owner_answer, owner_note와 공개 계약만 근거로 판단하며 '
                    '해당 답변에서 결론이 나지 않으면 unknown을 선택한다. dispute에서 주장하는 어긋남을 이 상황들로 '
                    '모두 구별할 수 있을 때만 covers_dispute를 true로 한다. 코드를 작성하거나 실행을 추측하지 않는다.')
            elif 'first_reading' in readback:
                instructions += '\n앞선 판독은 가설이다. source_path에서 선행 거부 조건, 해당 분기의 실행 가능성, 공통 후처리와 호출된 함수를 확인한다. 지적이 실제 가능한 입력에서 발생하는지 다시 판정한다. 실패가 먼저 거절되거나 공통 후처리가 요구 동작을 하면 그 근거 줄로 implemented를 선택한다. unresolved는 담당자가 운영 기준 자체를 결정하지 않은 경우에만 사용한다.'
        elif task_id(state) == 'allocation' and action == 'implement' and context['schedule_patch_required']:
            active = set(context.get('editable_decision_ids', []))
            ids = [d['request_id'] for d in context['scheduling_decisions'] if d['request_id'] in active]
            if ids:
                allowed = {'type':'string','enum':ids}
                passages = sorted({ref for d in context['scheduling_decisions'] if d['request_id'] in active
                                   for ref in allocation_repair.owner_passages(d)})
                fields = {**ALLOCATION_PATCH['properties']['edits']['items']['properties'],
                          'quote':{'type':'string','enum':passages}, 'request_id':allowed}
                choices = context['event_completions']
                use_choices = (len(ids)==1 and choices and
                               (context.get('response_feedback') or {}).get('error') !=
                               '요청한 조건에 맞는 기존 처리 조합이 없어 직접 편집이 필요합니다.')
                if use_choices:
                    fields.update(before={'type':'string','enum':list(dict.fromkeys(p['before'] for p in choices.values()))},
                                  after={'type':'string','enum':[*choices, '@custom']})
                edit = obj(fields)
                sites = {'maxItems':len(set(p['before'] for p in choices.values()))} if use_choices else {}
                checks = {**ALLOCATION_PATCH['properties']['checks'],'maxItems':0} if use_choices else ALLOCATION_PATCH['properties']['checks']
                schema = obj({**ALLOCATION_PATCH['properties'],'edits':{'type':'array','items':edit,**sites},'checks':checks})
                if use_choices:
                    instructions += '\n미구현 위치마다 성공 경로 한 개를 선택한다. 이미 거부 판정을 받은 사건은 이 위치에 도달하지 않는다. 선택한 변경은 실행기가 공개 계약으로 검사하므로 checks는 비운다.'
            else:
                schema = obj({**ALLOCATION_PATCH['properties'],
                              'edits':{**ALLOCATION_PATCH['properties']['edits'],'maxItems':0},
                              'checks':{**ALLOCATION_PATCH['properties']['checks'],'maxItems':0}})
                instructions += '\n이번에 다시 열린 결정이 없다. 기존 코드를 그대로 유지하고 현재 코드의 완료 여부만 판단한다.'
            instructions = instructions.replace('독립 Python 소스를 반환한다', '기존 Python 코드의 국소 편집을 반환한다')
            instructions = instructions.replace('전체 소스', '편집 목록') + ALLOCATION_PATCH_RULES
        can_ask = readback is None and (task_id(state) == 'cancellation_basic' or not state['config']['monitors'])
        if can_ask:
            schema = obj({**schema['properties'], 'requests': REQUESTS})
            directions = MAIN_QUESTIONS
            if task_id(state) == 'allocation' and context.get('schedule_patch_required'):
                directions = directions.replace('가능한 부분의 전체 소스를 제출한다', '확정된 부분의 편집만 제출한다')
            instructions += '\n' + directions
        try:
            result, metadata = client.invoke(envelope, instructions, schema)
        except Exception as exc:
            with self.cv:
                self._record_call_error(state, call, exc, ignored=not self._live_active(state, epoch))
                self._save(state)
            raise
        with self.cv:
            self._capture_response(state, call, result, metadata, epoch)
            if not self._live_active(state, epoch):
                raise RunStopped()
            if can_ask:
                validate_requests(result.get('requests'))
            call.update(status='completed')
            self._save(state)
        return result, envelope

    def _live_observe(self, state):
        if not state['monitors']:
            return
        # Called while holding cv; observers receive the same immutable snapshot.
        snapshot = copy.deepcopy(self._live_context(state))
        snapshot.pop('pending_reviews', None)
        for config in state['config']['monitors']:
            envelope = agent_input('monitor', config, snapshot, 'observe')
            call = {'id':uuid.uuid4().hex, 'agent': 'monitor-%s' % config['id'], 'input': envelope, 'status': 'running',
                    'started_at':timestamp(), 'stage':'api_request', 'execution_epoch':state.get('execution_epoch', 0)}
            state['calls'].append(call)
            state['monitors'][config['id'] - 1]['status'] = 'observing'
            self.pool.submit(self._live_monitor, state['id'], config['id'], envelope, call, self.api_client, state.get('execution_epoch', 0))

    def _live_monitor(self, run_id, monitor_id, envelope, call, client, epoch):
        try:
            with self.cv:
                if not self._live_active(self._state(run_id), epoch):
                    return
                selected_task = task_id(self._state(run_id))
            schema = schemas_for(selected_task)[1]
            instructions = monitor_rules(selected_task)
            if selected_task=='allocation':
                schema = obj({**schema['properties'],'checks':{**schema['properties']['checks'],'maxItems':0}})
                instructions += '\n이번 단계에서는 판단과 이유만 제출하고 checks는 비운다. 구체적인 실행 검사가 필요하면 verify를 선택한다. 그 경우 이어지는 요청에서 담당자가 확정한 정책에 근거한 검사만 제출한다.'
            result, metadata = client.invoke(envelope, instructions, schema)
            with self.cv:
                state = self._state(run_id)
                self._capture_response(state, call, result, metadata, epoch)
                if not self._live_active(state, epoch):
                    return
            result = self._route_review(result)
            if selected_task=='allocation' and result.get('decision')=='verify' and not result.get('checks'):
                checks=self._schedule_monitor_checks(run_id,monitor_id,envelope,client,epoch,result['reason'])
                result=dict(result,checks=checks)
            validate_monitor(result)
            decision = result.get('decision')
            items = result.get('requests')
            checks = result.get('checks')
            code = envelope['project_state']['code']
            verification = self._public_verification(code, checks, selected_task) if checks and code else None
            if (selected_task=='allocation' and decision=='verify' and verification
                    and not verification['total'] and verification.get('rejected_checks')):
                reasons=' / '.join(r['reason'] for r in verification['rejected_checks'])[:500]
                checks=self._schedule_monitor_checks(run_id,monitor_id,envelope,client,epoch,
                    result['reason']+' · 제시한 검사 자체의 공개 규격을 고쳐 주세요. '+reasons)
                result=dict(result,checks=checks)
                verification=self._public_verification(code,checks,selected_task)
                if not verification['total'] and verification.get('rejected_checks'):
                    raise ValueError('감시자가 요청한 검사를 공개 규격에 맞게 구성하지 못했습니다.')
            with self.cv:
                state = self._state(run_id)
                if not self._live_active(state, epoch):
                    return
                call.update(status='completed')
                if verification is not None:
                    call['verification'] = verification
                monitor = state['monitors'][monitor_id - 1]
                version = envelope['project_state']['code_version']
                entry = self._record_review(state, call, monitor_id, version, result, verification)
                ids = self._register_requests(state, items, monitor_id, version)
                entry['request_ids'] = list(dict.fromkeys(entry.get('request_ids', []) + ids))
                if monitor['version'] is not None and version < monitor['version']:
                    self._save(state)
                    return
                monitor.update(status='observed', decision=decision, version=version,
                               reason=result['reason'], verification=verification, last_call_id=call['id'])
                self._live_task_status(state)
                self._save(state)
        except Exception as exc:
            with self.cv:
                state = self._state(run_id)
                self._record_call_error(state, call, exc, ignored=not self._live_active(state, epoch))
                if self._live_active(state, epoch):
                    state['monitors'][monitor_id - 1].update(status='error', reason=safe_log(str(exc)))
                    self._pause_live_error(state, '감시 %s 오류: %s' % (monitor_id, str(exc)))
                else:
                    self._save(state)

    def _schedule_monitor_checks(self, run_id, monitor_id, original, client, epoch, reason):
        project=original['project_state']
        public=dict(task=project['task'],code_version=project['code_version'],
                    scheduling_decisions=project['scheduling_decisions'],reason=reason)
        envelope=dict(original,action='specify_schedule_checks',project_state=public)
        with self.cv:
            state=self._state(run_id)
            if not self._live_active(state,epoch):
                raise RunStopped()
            call=dict(id=uuid.uuid4().hex,agent=f'monitor-{monitor_id}',input=envelope,status='running',
                      started_at=timestamp(),stage='api_request',execution_epoch=epoch)
            state['calls'].append(call)
            self._save(state)
        try:
            check_array=schemas_for('allocation')[1]['properties']['checks']
            reply,meta=client.invoke(envelope,'앞서 요청한 검사의 입력과 기대 결과를 공개 계약과 담당자 답으로 작성한다. '
                '입력은 initial_state·events 객체의 JSON 문자열이고 기대 결과는 공개 출력 규격 전체를 갖춘 JSON 문자열이다.',
                obj({'checks':{**check_array,'minItems':1,'maxItems':10}}))
            with self.cv:
                state=self._state(run_id)
                self._capture_response(state,call,reply,meta,epoch)
                if not self._live_active(state,epoch):
                    raise RunStopped()
                checks=reply.get('checks')
                if not isinstance(checks,list) or not 1<=len(checks)<=10:
                    raise ValueError('감시자가 요청한 공개 실행 검사가 누락됐습니다.')
                call['status']='completed'
                self._save(state)
                return checks
        except Exception as exc:
            with self.cv:
                self._record_call_error(state,call,exc,ignored=not self._live_active(state,epoch))
                self._save(state)
            raise

    @staticmethod
    def _route_review(result):
        # Keep the original model output on the call. A prose request is forwarded verbatim.
        if not isinstance(result, dict):
            return result
        if (isinstance(result.get('requests'), list) and result['requests']
                and result.get('decision') in ('continue', 'verify')):
            return dict(result, decision='human')
        if result.get('requests') != []:
            return result
        reason = result.get('reason')
        if not isinstance(reason, str) or not reason.strip():
            return result
        explicit = re.search(r'(?:인가요|하나요|할까요|됩니까|나요|습니까)[?？]|'
                             r'(?:확인|문의|질문)해\s*(?:주세|주십|주시)|(?:확인|질문|문의)이 필요(?:합|하[다며])|'
                             r'(?:담당자|운영자).{0,60}(?:물어봐야|확인해야|알려달)', reason)
        if result.get('decision') != 'human' and not (result.get('decision') in ('continue', 'verify') and explicit):
            return result
        key = 'review_' + hashlib.sha256(reason.encode()).hexdigest()[:24]
        return dict(result, decision='human', requests=[dict(key=key, question=reason[:2000], reason='감시 의견 원문에서 전달',
                                                            priority='normal', affected_tasks=['policy'])])

    def _record_review(self, state, call, monitor_id, version, result, verification):
        raw = json.dumps([monitor_id, result], ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(raw.encode()).hexdigest()
        call['review_id'] = key
        log = state.setdefault('review_log', [])
        entry = next((r for r in log if r['id'] == key), None)
        if entry is None:
            entry = dict(id=key, monitor_id=monitor_id, version=version, **copy.deepcopy(result))
            log.append(entry)
        entry['latest_version'] = max(entry.get('latest_version', version), version)
        # A failed check against different code is new evidence even when the wording repeats.
        if (verification and not verification['passed'] and (verification['total'] or verification.get('error'))
                and version >= entry['latest_version']):
            entry.pop('delivered_version', None)
            entry['verification'] = verification
        if (task_id(state) == 'allocation' and version >= entry['latest_version']
                and set(result.get('affected_decision_ids', [])) & {d['request_id'] for d in state['decisions']}):
            entry.pop('delivered_version', None)
        return entry

    def _restore_review_log(self, state):
        for call in state['calls']:
            if (not call['agent'].startswith('monitor-') or call['status'] != 'completed'
                    or call['input'].get('action')=='specify_schedule_checks'
                    or call.get('review_id') or not isinstance(call.get('output'), dict)):
                continue
            monitor_id = int(call['agent'].split('-')[1])
            version = call['input']['project_state']['code_version']
            result = self._route_review(call['output'])
            validate_monitor(result)
            entry = self._record_review(state, call, monitor_id, version, result, None)
            entry['request_ids'] = self._register_requests(state, result['requests'], monitor_id, version)

    def _register_requests(self, state, items, source, version):
        ids = []
        for item in items:
            existing = next((r for r in state['requests'] if r['key'] == item['key'] and r['question'] == item['question']), None)
            if existing:
                if source not in existing['sources']:
                    existing['sources'].append(source)
                ids.append(existing['id'])
                continue
            state['requests'].append({**item, 'id': uuid.uuid4().hex, 'sources': [source],
                                      'status': 'waiting', 'answer': None, 'observed_version': version,
                                      'fields': [{'name': 'text', 'type': 'text', 'label': '답변'}]})
            self._event(state, item['question'], 'main' if source == 'main' else 'monitor-%s' % source)
            ids.append(state['requests'][-1]['id'])
        return ids

    def _can_reuse_reviews(self, state, envelope, result):
        previous = envelope['project_state']
        verified = state['verification'] if task_id(state) == 'allocation' else previous.get('verification')
        if (not previous.get('pending_reviews') or result['code'] != previous['code'] or result.get('requests')
                or not (verified or {}).get('passed') or state['decisions'] != previous['decisions']):
            return False
        calls = {c['id']: c for c in state['calls'] if c.get('id')}
        for monitor in state['monitors']:
            call = calls.get(monitor.get('last_call_id'))
            if (monitor['version'] != previous['code_version'] or monitor['status'] != 'observed' or not call
                    or call['input']['project_state']['decisions'] != state['decisions']):
                return False
            if task_id(state) == 'allocation' and (call.get('output') or {}).get('affected_decision_ids'):
                return False
        return True

    def _live_task_status(self, state):
        affected = {task for r in state['requests'] if r['status'] in ('waiting', 'answered', 'applying', 'needs_example', 'check_failed') for task in r['affected_tasks']}
        for task in state['tasks']:
            task['status'] = 'blocked' if task['id'] in affected else ('running' if state['code_version'] else 'pending')

    def _work_live(self, run_id, resume=False, epoch=0):
        try:
            with self.cv:
                state = self._state(run_id)
                selected_task = task_id(state)
                definition = TASKS[selected_task]
                if resume:
                    self._restore_review_log(state)
                needs_plan = not resume or not state['plan']
            if needs_plan:
                plan, _ = self._live_call(run_id, 'plan', PLAN, epoch)
                if not isinstance(plan.get('plan'), list) or not all(isinstance(x, str) for x in plan['plan']) or not isinstance(plan.get('assumptions'), list):
                    raise ValueError('계획 응답 형식 오류')
            with self.cv:
                if not self._live_active(state, epoch):
                    return
                if needs_plan:
                    state['plan'], state['assumptions'] = plan['plan'], plan['assumptions']
                    self._register_requests(state, plan.get('requests', []), 'main', state['code_version'])
                    self._live_task_status(state)
                self._live_observe(state)
                self._save(state)
            autonomous_steps = 0
            while True:
                with self.cv:
                    if not self._live_active(state, epoch):
                        return
                    # Human feedback starts a fresh work cycle; it is never charged
                    # against the consecutive autonomous-revision budget.
                    if any(r['status'] == 'answered' for r in state['requests']):
                        autonomous_steps = 0
                    elif autonomous_steps >= self.MAX_AUTONOMOUS_STEPS:
                        state.update(status='paused', phase='자동 수정 한도 · 계속하기 대기', pause_reason='autonomous_limit')
                        self._event(state, '새 인간 답변 없이 자동 수정 %s회 진행했습니다. 답변 입력은 가능하며 계속하기로 이어갈 수 있습니다.' % self.MAX_AUTONOMOUS_STEPS)
                        self._save(state)
                        return
                    else:
                        autonomous_steps += 1
                    state['autonomous_steps'] = autonomous_steps
                    state.update(status='running', phase='코드 작성·수정')
                    self._save(state)
                result, envelope = self._live_implement(run_id, selected_task, epoch)
                code = result.get('code')
                if not isinstance(code, str) or len(code) > 100000:
                    raise ValueError('생성 코드 크기·형식 오류')
                if type(result.get('complete')) is not bool:
                    raise ValueError('완료 판단 형식 오류')
                decisions = envelope['project_state']['decisions']
                answers_used = {d['request_id']: d['answer'] for d in decisions}
                checks = result.get('checks')
                if selected_task == 'allocation' and checks==[] and envelope['project_state']['code']==code:
                    checks = state.get('scheduling_last_checks',[])
                verification = self._verify_revision(code, checks, selected_task, decisions)
                with self.cv:
                    if not self._live_active(state, epoch):
                        return
                    state['code_version'] += 1
                    version = state['code_version']
                    filename = 'solution_v%s.py' % version
                    (self.data / run_id / filename).write_text(code)
                    state['artifact'] = {'filename': filename, 'code': code, 'sha256': hashlib.sha256(code.encode()).hexdigest()}
                    if selected_task == 'allocation' and decisions:
                        state['scheduling_initialized'] = True
                        state.pop('scheduling_draft',None)
                        state['scheduling_last_checks']=checks
                    state['verification'] = {'type': 'syntax_and_public_checks', 'code_version': version, **verification,
                                             'note': '이 코드 버전의 공개 검사 결과입니다. 최종 정확도는 별도 채점합니다.'}
                    sent = {r['id'] for r in envelope['project_state'].get('pending_reviews', [])}
                    for review in state.get('review_log', []):
                        if review['id'] in sent and review.get('latest_version', 0) <= envelope['project_state']['code_version']:
                            review['delivered_version'] = version
                    for request in state['requests']:
                        key = request['id']
                        if key not in answers_used or request['answer'] != answers_used[key]:
                            continue
                        if key in verification['decision_status']:
                            if verification['decision_status'][key]:
                                request.update(status='applied', applied_version=version, verified_version=version)
                            else:
                                request.update(status='check_failed')
                                request.pop('applied_version', None)
                                request.pop('verified_version', None)
                        elif key in verification['needs_examples']:
                            request.update(status='needs_example')
                            request.pop('applied_version', None)
                            request.pop('verified_version', None)
                        elif request['status'] == 'answered':
                            if (request['id'] in result.get('context_decision_ids', [])
                                    or selected_task == 'cancellation_basic' and context_only(request['answer']['text'])):
                                request.update(status='acknowledged', acknowledged_version=version)
                            else:
                                request.update(status='applied', applied_version=version)
                    self._event(state, '코드 v%s 작성 · 자체 검증 %s/%s' % (version, verification['correct'], verification['total']), 'main')
                    self._register_requests(state, result.get('requests', []), 'main', version)
                    self._live_task_status(state)
                    # A handoff that returns identical code under identical decisions keeps its observations.
                    if self._can_reuse_reviews(state, envelope, result):
                        for monitor in state['monitors']:
                            monitor['version'] = version
                    else:
                        self._live_observe(state)
                    state['phase'] = '감시 검토' if state['monitors'] else '메인 자체 검증'
                    self._save(state)
                while True:
                    with self.cv:
                        if not self._live_active(state, epoch):
                            return
                        if any(r['status'] == 'answered' for r in state['requests']):
                            break  # Apply early answers immediately, without a monitor barrier.
                        waiting = any(r['status'] in ('waiting', 'needs_example') for r in state['requests'])
                        reviewed = all(m['version'] == version and m['status'] == 'observed' for m in state['monitors'])
                        reviewed = reviewed and not any(c['agent'].startswith('monitor-') and c['status'] == 'running'
                            and c.get('execution_epoch', 0) == epoch for c in state['calls'])
                        if reviewed and not waiting:
                            final = state['verification']
                            for monitor in state['monitors']:
                                checked = monitor.get('verification')
                                if checked is None:
                                    continue
                                final['correct'] += checked['correct']
                                final['total'] += checked['total']
                                final['results'].extend(dict(r, monitor_id=monitor['id']) for r in checked['results'])
                                if checked.get('error'):
                                    final['error'] = checked['error']
                            update_verification(final)
                            pending = any(r.get('delivered_version') is None for r in state.get('review_log', []))
                            repair_closed = (selected_task=='allocation' and final['passed']
                                             and self._reviewed_schedule_repair(state,envelope,result))
                            if (result['complete'] and final['passed'] and not pending) or repair_closed:
                                if repair_closed:
                                    state['completion_basis']='confirmed_owner_decisions_and_current_observers'
                                state.update(status='completed', phase='프로젝트 완료')
                                for task in state['tasks']:
                                    task['status'] = 'completed'
                                self._event(state, '프로젝트 완료. 테스트하기로 %s문항을 채점할 수 있습니다.' % definition['total'])
                                self._save(state)
                                return
                            break
                        desired = 'waiting' if waiting else 'running'
                        if state['status'] != desired:
                            state.update(status=desired, phase='인간 판단 대기' if waiting else '감시 검토')
                            self._save(state)
                        self.cv.wait(timeout=1)
        except RunStopped:
            return
        except Exception as exc:
            with self.cv:
                state = self._state(run_id)
                if self._live_active(state, epoch):
                    call = next((c for c in reversed(state['calls']) if c['agent'] == 'main' and c.get('execution_epoch', 0) == epoch), None)
                    self._record_call_error(state, call, exc)
                    self._pause_live_error(state, '작업 오류: ' + str(exc))
