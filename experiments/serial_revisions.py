"""Carry requirement-linked changes through one versioned program without intermediate execution."""
from collections import Counter
from experiments import rule_edits as rules
from experiments.blind_candidates import SEEDS as PREVIOUS, digest, validate_batch
from experiments.local_baseline import submission_text
from experiments.monitor_cycles import MAIN, MODEL, SUBMIT, compact, locked_output, public_brief, read, recorded, save
from experiments.source_revisions import SourceRevisions, public_quantities


FRESH = (307, 331, 353, 379, 401, 419)
SEEDS = PREVIOUS + FRESH
ARMS = ('direct', 'self_plan', 'self_final', 'B', 'C', 'abcd')
LIMIT = 1152
PLAN_GUIDE = (
    '고객 안내문 각 문장의 ID에 해당하는 일반 규칙을 설계합니다. ID마다 rank(작은 수가 먼저, '
    '동률은 원문 순), branches, assumption을 채우세요. branches의 각 행은 when의 비교식을 모두 만족하면 '
    'allow를 즉시 반환합니다. 여러 행은 위에서부터 적용하며 otherwise는 최종 기본값입니다. '
    '각 비교식은 입력 이름, 비교 연산자, 정수 초 단위 경계값입니다. 시간의 기준점과 단위를 구분하세요. '
    '명세가 인정한 동작은 실제 조건과 반환으로 표현하세요. 수치나 우선순위가 비어 있으면 구현에 필요한 '
    '가정을 스스로 정하고 assumption에 표시하세요. 명시된 값과 가정한 값을 구분하세요. '
    '다른 행이나 기본값이 그 규칙을 이미 처리한다면 빈 branches와 그 이유를 남길 수 있습니다. '
    '한국어 설명은 항목당 한 문장으로 짧게 쓰세요.'
)
PATCH_GUIDE = (
    '바로 앞 규칙표를 부분 수정하세요. 각 원문 ID와 otherwise에 대해 정확히 한 가지를 선택합니다. '
    '보존하려면 {"keep":"근거"}, 바꾸려면 {"set":교체할 항목 전체,"reason":"수정 이유"}를 씁니다. '
    '지적한 결함을 고치려면 해당 위치의 비교식·순서·반환을 직접 교체하세요. '
    '주석만 바꾸고 동작을 고쳤다고 쓰지 마세요. 이미 목적에 맞는 부분은 보존하세요.'
)
ANALYZE = (
    '초안을 보기 전에 사용자 명세를 해석하세요. 원문 ID별로 실제로 달라져야 하는 판정(intent), '
    '그 판정을 결정하는 함수 입력(inputs), 원문만으로 확정할 수 없는 내용(unspecified)을 분리하세요. '
    '기간이 명시되지 않은 경우 수치를 발명하지 마세요. 각 설명은 한 문장이면 됩니다.'
)
REVIEW = '원문과 앞 단계 요구 해석을 대조하세요. 언급만 되고 코드에 없는 요구를 찾아 실제 분기에 반영하세요.'
INTERACTIONS = '앞선 return이 예외를 가리는지, 변수의 기준점과 분기 순서가 맞는지 검토해 필요한 부분을 고치세요.'
SIGN_OFF = ('최종 통합 책임자입니다. 원문 ID별로 현재 코드가 요구를 실제로 처리하는지 첫 반환까지 읽으세요. '
            '직전 수정의 목적을 보존하고 남은 누락이나 충돌은 해당 항목에서 직접 고치세요.')
AMEND_GUIDE = (
    '기존 함수에서 달라져야 하는 부분만 원문 ID별 조건으로 작성합니다. 각 행의 at으로 원래의 반환 위치 '
    '(E ID)를 선택하면 그 return 바로 전에만 조건을 삽입합니다. 모든 경로에 공통으로 필요한 경우에만 '
    'ENTRY를 선택하세요. 고칠 필요 없는 문장은 branches를 비우세요. 기존 본문까지 함께 고려해 '
    '각 수정이 필요한 상황에만 적용되도록 하세요. 특히 기존 판단을 넓혀야 할 때와 좁혀야 할 때를 구분하세요. '
    '각 ID의 rank는 작은 수가 먼저이고 동률은 원문 순입니다. branches의 각 행은 when을 모두 만족하면 '
    'allow를 반환합니다. 명세에 적힌 수량을 비교할 때 bound에는 해당 T ID를 쓰세요. 그 밖의 값은 '
    'amount와 unit을 함께 쓰세요. 미명시 수치는 한 가지 현실적인 기간을 가정하고 assumption에 출처를 '
    '밝히세요. 미명시 수치를 이유로 명시된 동작 전체를 누락하지 마세요. 설명은 한 문장으로 짧게 쓰세요.'
)
AMEND_PATCH = (
    '직전에 작성한 수정 조건을 이어서 검토하세요. 각 ID의 조건이 이미 적절하면 {"keep":"유지 근거"}, '
    '바꿀 경우 {"set":교체할 항목 전체,"reason":"구체적 변경 이유"}를 제출하세요. '
    '지적한 변경은 비교식·반환·순서에 직접 반영하세요. 다른 항목은 그대로 보존됩니다.'
)
SERIAL_STEPS = [('B', '당신은 변경을 설계하고 구현하는 개발자입니다.', REVIEW, 'B'),
                ('C', '당신은 누락과 분기 충돌을 수정하는 검토자입니다.', INTERACTIONS, 'C'),
                ('D', '당신은 최종 코드 통합 책임자입니다.', SIGN_OFF, 'abcd')]
SELF_STEPS = [('plan', MAIN, REVIEW, 'self_plan'), ('review1', MAIN, REVIEW, None),
              ('review2', MAIN, INTERACTIONS, None), ('final', MAIN, SIGN_OFF, 'self_final')]


def response_format(schema):
    return {'type':'json_schema', 'json_schema':{'strict':True, 'name':'review_document', 'schema':schema}}


def json_call(path, role, system, user, schema, seed, port):
    response = recorded(path, role, system, user, seed, LIMIT, port, response_format(schema))
    return rules.decode(response['text'], schema), response['finish_reason']


def snapshot(seed, arm, code, calls):
    return dict(seed=seed, arm=arm, chosen=arm, code=code, sha256=digest(code), calls=list(calls))


def revision_context(draft, context, amendment, interpretation):
    base_context = dict(context)
    if interpretation is not None:
        base_context['A의 요구 해석'] = interpretation
    base_context['초안의 실행문과 입력 참조'] = rules.inspect_draft(draft)
    if amendment:
        base_context['원문 수량 참조'] = amendment.quantities
        base_context['수정 가능한 위치'] = amendment.sites
        if amendment.has_base:
            base_context['초안의 실행문과 입력 참조']['function'] = amendment.annotated
        base_context['추가 조건 밖의 처리'] = ('원래 함수 본문을 그대로 사용' if amendment.has_base
                                            else '초안 함수를 읽을 수 없어 otherwise로 기본 반환을 지정')
    return base_context


def stage_prompt(context, instruction, plan, code, last_decisions, amendment, clauses):
    guide, patch = (AMEND_GUIDE, AMEND_PATCH) if amendment else (PLAN_GUIDE, PATCH_GUIDE)
    if plan is None:
        return compact(context)+'\n'+instruction+'\n'+guide
    notes = amendment.notes(plan) if amendment else rules.source_notes(plan, clauses)
    packet = dict(context, 현재_규칙표=plan, 현재_코드=code, 직전_수정_근거=last_decisions, 소스에서_읽은_정보=notes)
    return compact(packet)+'\n'+instruction+'\n'+guide+'\n'+patch


def revise(d, seed, port, arm, draft, shared_call, context, clauses, amendment=None):
    """Both arms get four sequential calls after the draft. Only the treatment has the independent spec reader."""
    directory = d/arm
    directory.mkdir(exist_ok=True)
    steps = SERIAL_STEPS if arm == 'serial' else SELF_STEPS
    calls = [shared_call]
    interpretation = None
    if arm == 'serial':
        agent_path = directory/'A.json'
        schema = rules.obj(dict.fromkeys(clauses, rules.INTERPRETATION))
        agent, finish = json_call(agent_path, 'A', '당신은 명세를 해석하는 요구사항 담당자입니다.',
                                 compact(context)+'\n'+ANALYZE, schema, seed, port)
        calls.append(str(agent_path.relative_to(d)))
        interpretation = agent if agent is not None else {'응답 형식 미완료':finish}
    base_context = revision_context(draft, context, amendment, interpretation)
    fields = amendment.slots if amendment else rules.slots(clauses)
    plan, code = None, draft
    journal, submissions = [], []
    last_decisions = {}
    for role, system, instruction, arm_name in steps:
        callpath = directory/f'{role}.json'
        before = digest(code)
        schema = rules.obj(fields) if plan is None else rules.patch_slots(fields)
        prompt = stage_prompt(base_context, instruction, plan, code, last_decisions, amendment, clauses)
        payload, finish = json_call(callpath, role, system, prompt, schema, seed, port)
        calls.append(str(callpath.relative_to(d)))
        receipt = {}
        if payload is None:
            state = 'unapplied_invalid_document'
        elif plan is None:
            plan = payload
            state = 'created'
        else:
            plan, receipt = rules.apply_edits(plan, payload)
            last_decisions = {k: {'status':v['status'], 'reason':v['reason']} for k,v in receipt.items()}
            state = 'reviewed'
        if plan is not None:
            code, locations = amendment.render(plan) if amendment else rules.render(plan, clauses)
        else:
            locations = {}
        journal.append(dict(role=role, state=state, finish=finish, request_file=calls[-1],
                            before_sha256=before, after_sha256=digest(code), plan=plan,
                            edits=receipt, source_lines=locations))
        if arm_name:
            submissions.append(snapshot(seed, arm_name, code, calls))
        save(directory/'changes.json', journal)
    return submissions


def generate_seed(out, seed, index, port, preserve_original=True):
    d = out/str(seed)
    d.mkdir(exist_ok=True)
    brief = public_brief()
    clauses = rules.notice_clauses(brief)
    context = {'공개 명세':brief, '원문 ID':clauses}
    draft_path = d/'draft.json'
    draft = submission_text(recorded(draft_path, 'main', MAIN, brief+'\n\n'+SUBMIT, seed, 1500, port)['text'])
    amendment = SourceRevisions(draft, clauses) if preserve_original else None
    batch = [snapshot(seed, 'direct', draft, [draft_path.name])]
    for arm in (('serial', 'self') if index % 2 == 0 else ('self', 'serial')):
        batch.extend(revise(d, seed, port, arm, draft, draft_path.name, context, clauses, amendment))
        print('fixed', seed, arm, flush=True)
    return batch


def verify_request(call, seed, role, system, prompt, limit, schema=None):
    request = dict(model=MODEL, messages=[dict(role='system',content=system),dict(role='user',content=prompt)],
                   seed=seed, temperature=0.3, top_p=0.9, top_k=40, max_tokens=limit,
                   stream=False, chat_template_kwargs={'enable_thinking':False})
    if schema is not None:
        request['response_format'] = response_format(schema)
    if call['request'] != request or call['model'] != MODEL or call['role'] != role:
        raise ValueError(f'{seed}/{role}: 공개 자료로 재구성한 요청과 모델 설정이 원본 기록과 다릅니다.')


def verify_seal(out, seeds, preserve_original):
    """Replay receipts against the raw responses and exact text submitted, without executing candidates."""
    batch = read(out/'submissions.json')
    validate_batch(batch, seeds, ARMS)
    by_arm = {(r['seed'],r['arm']): r for r in batch}
    brief = public_brief()
    clauses = rules.notice_clauses(brief)
    context = {'공개 명세':brief, '원문 ID':clauses}
    counts = Counter()
    if (out/'shared-inputs.json').is_file():
        paired = read(out/'shared-inputs.json')
        names = [f'{s}/{filename}' for s in seeds for filename in ('draft.json','serial/A.json')]
        expected_hashes = {name:digest(compact(read(out/name))) for name in names}
        if paired != dict(source_protocol='serial-rule-edits-v1', raw_call_hashes=expected_hashes):
            raise ValueError('공통 초안 또는 A의 원문 해시와 입력 기록이 다릅니다.')
        counts['shared_raw_calls'] = len(names)
    for seed in seeds:
        d = out/str(seed)
        draft_call = read(d/'draft.json')
        verify_request(draft_call, seed, 'main', MAIN, brief+'\n\n'+SUBMIT, 1500)
        draft = submission_text(draft_call['text'])
        if by_arm[seed,'direct'] != snapshot(seed, 'direct', draft, ['draft.json']):
            raise ValueError('초안 응답과 고정 제출이 다릅니다.')
        adapter = SourceRevisions(draft, clauses) if preserve_original else None
        fields = adapter.slots if adapter else rules.slots(clauses)
        for arm in ('self', 'serial'):
            directory = d/arm
            log = read(directory/'changes.json')
            steps = SERIAL_STEPS if arm == 'serial' else SELF_STEPS
            if [s['role'] for s in log] != [role for role, *_ in steps]:
                raise ValueError('고정 호출 순서와 수정 이력이 일치하지 않습니다.')
            plan, code = None, draft
            interpretation, last_decisions = None, {}
            calls = ['draft.json'] + (['serial/A.json'] if arm == 'serial' else [])
            if arm == 'serial':
                a_call = read(directory/'A.json')
                schema = rules.obj(dict.fromkeys(clauses, rules.INTERPRETATION))
                verify_request(a_call, seed, 'A', '당신은 명세를 해석하는 요구사항 담당자입니다.',
                               compact(context)+'\n'+ANALYZE, LIMIT, schema)
                analysis = rules.decode(a_call['text'], schema)
                if analysis is None:
                    counts['incomplete_analyses'] += 1
                interpretation = analysis if analysis is not None else {'응답 형식 미완료':a_call['finish_reason']}
            base_context = revision_context(draft, context, adapter, interpretation)
            for step, (role, system, instruction, name) in zip(log, steps):
                call = read(directory/f'{role}.json')
                calls.append(f'{arm}/{role}.json')
                prompt = stage_prompt(base_context, instruction, plan, code, last_decisions, adapter, clauses)
                schema = rules.obj(fields) if plan is None else rules.patch_slots(fields)
                verify_request(call, seed, role, system, prompt, LIMIT, schema)
                if (step['before_sha256'] != digest(code) or step['request_file'] != calls[-1]
                        or step['finish'] != call['finish_reason']):
                    raise ValueError('수정 이력과 원문 응답이 일치하지 않습니다.')
                document = rules.decode(call['text'], schema)
                expected_edits = {}
                if document is None:
                    state = 'unapplied_invalid_document'
                    counts['unapplied_documents'] += 1
                elif plan is None:
                    state, plan = 'created', document
                else:
                    state = 'reviewed'
                    plan, expected_edits = rules.apply_edits(plan, document)
                    last_decisions = {k:{'status':v['status'], 'reason':v['reason']} for k,v in expected_edits.items()}
                    counts.update(v['status'] for v in expected_edits.values())
                if step['state'] != state or step['edits'] != expected_edits or step['plan'] != plan:
                    raise ValueError('원문에서 복원한 수정·유지 내역과 기록이 다릅니다.')
                code, locations = ((adapter.render(plan) if adapter else rules.render(plan, clauses))
                                   if plan is not None else (draft, {}))
                if digest(code) != step['after_sha256'] or locations != step['source_lines']:
                    raise ValueError('규칙에서 복원한 함수와 반영 이력이 다릅니다.')
                counts['stages'] += 1
                if name and by_arm[seed,name] != snapshot(seed, name, code, calls):
                    raise ValueError('제출 코드 또는 호출 경로가 원문과 다릅니다.')
    return dict(counts, submissions=len(batch))


def share_inputs(source, out):
    """Pair the two methods on *only* the raw draft and A call. recorded() also checks exact prompts on use."""
    source_design = read(source/'design.json')
    if source_design['protocol'] != 'serial-rule-edits-v1' or source_design['model'] != MODEL:
        raise ValueError('같은 모델의 전체 규칙표 대조 실행이 필요합니다.')
    hashes = {}
    for seed in SEEDS:
        for name in ('draft.json', 'serial/A.json'):
            relative = f'{seed}/{name}'
            call = read(source/relative)
            request = call['request']
            sampling = (request['temperature'], request['top_p'], request['top_k'], request['chat_template_kwargs'])
            if sampling != (0.3, 0.9, 40, {'enable_thinking':False}) or call['model'] != MODEL:
                raise ValueError('공통 호출의 모델 설정이 다릅니다.')
            dest = out/relative
            if dest.exists() and read(dest) != call:
                raise ValueError(f'기존 응답을 덮어쓸 수 없습니다: {relative}')
            dest.parent.mkdir(parents=True, exist_ok=True)
            save(dest, call)
            hashes[relative] = digest(compact(call))
    save(out/'shared-inputs.json', dict(source_protocol=source_design['protocol'], raw_call_hashes=hashes))


def design_for(preserve_original):
    design = dict(protocol='serial-source-edits-v2' if preserve_original else 'serial-rule-edits-v1',
                  model=MODEL, information='public',
                  previously_used=list(PREVIOUS), new=list(FRESH), arms=list(ARMS),
                  fixed_calls=dict(direct=1, self_plan=2, self_final=5, B=3, C=4, abcd=5),
                  notice=rules.notice_clauses(public_brief()), max_tokens_after_draft=LIMIT,
                  constraints='source and syntax only; no example execution, hidden labels, or score-based routing',
                  evaluation='seal all six snapshots for every seed, then grade 40 and 56 inputs')
    if preserve_original:
        design.update(public_quantities=public_quantities(design['notice']),
                      static_review='source-only interval containment, necessary if/return paths and redundant literal returns',
                      amendment='insert only targeted guards at a specified original return or entry; preserve the original AST; '
                                'explicit basic units or references from the public notice')
    return design


def prepare_seal(out, port, preserve_original=True, shared_inputs_from=None):
    design = design_for(preserve_original)
    with locked_output(out):
        path = out/'design.json'
        if (path.exists() and read(path) != design) or (not path.exists() and any(out.iterdir())):
            raise ValueError('새 폴더 또는 동일 설계의 실행 기록을 사용하세요.')
        save(path, design)
        seal = out/'submissions.json'
        if not seal.exists():
            if (out/'results.json').exists() or any(out.glob('*/*-score.json')):
                raise ValueError('채점이 시작된 폴더에서 새 제출을 생성할 수 없습니다.')
            if shared_inputs_from is not None:
                share_inputs(shared_inputs_from, out)
            batch = []
            for index, seed in enumerate(SEEDS):
                batch.extend(generate_seed(out, seed, index, port, preserve_original))
            validate_batch(batch, SEEDS, ARMS)
            save(seal, batch)


def evaluate_seal(out, preserve_original=True):
    """The CLI has stopped the inference server before this phase; no model calls are possible here."""
    from experiments.blind_candidates import grade_sealed
    from experiments.revision_summary import summarize
    with locked_output(out):
        if read(out/'design.json') != design_for(preserve_original):
            raise ValueError('확정한 제출과 채점하려는 실험의 설계가 다릅니다.')
        save(out/'integrity.json', verify_seal(out, SEEDS, preserve_original))
        grade_sealed(out, SEEDS, ARMS)
        save(out/'comparisons.json', summarize(out))
