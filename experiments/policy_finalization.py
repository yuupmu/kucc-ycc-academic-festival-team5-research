"""A fixed, task-specific final review separating the two clocks in the public notice."""
from collections import Counter

from experiments import rule_edits as rules
from experiments.blind_candidates import digest, validate_batch
from experiments.local_baseline import submission_text
from experiments.monitor_cycles import MAIN, MODEL, compact, locked_output, public_brief, read, save
from experiments import serial_revisions as prior
from experiments.source_revisions import SourceRevisions, UNIT_SECONDS, public_quantities


SEEDS, LIMIT = prior.SEEDS, prior.LIMIT
ARMS = ('direct', 'self_before', 'abcd_before', 'self_final', 'abcd')
PREFIX = {'self': ('plan','review1','review2','final'), 'serial': ('A','B','C','D')}
NAMES = {'self':('self_before','self_final'), 'serial':('abcd_before','abcd')}
SCOPE = ('before_start', 'through_start', 'also_after_start')
FORM = rules.obj({
    'ordinary_at_deadline':rules.BOOL,
    'correction_window':rules.obj({'amount':{'type':'integer','minimum':1},
                                  'unit':{'type':'string','enum':list(UNIT_SECONDS)}}),
    'correction_at_window_end':rules.BOOL,
    'correction_scope':{'type':'string','enum':list(SCOPE)},
    'reasons':rules.obj({key:rules.TEXT for key in ('R1','R2','R3')}),
})
INSTRUCTION = (
    '이번 최종 검토에서는 서로 다른 두 시계를 분리하세요. R1 수량은 이용 시작을 기준으로 한 일반 취소 마감입니다. '
    'R2의 이용 시작 시점은 함수 계약에 적혀 있습니다. R3의 정정 기간은 예약 이후의 경과 시간이고 원문에 수치가 없습니다. '
    '이전 코드가 R1의 기간을 R3에 가져왔다면 근거를 다시 검토하세요. “방금”이라는 공개 문구에 맞는 기간을 '
    '스스로 가정해 amount와 unit에 명시하세요. 일반 마감 정확히 그 순간 허용 여부(ordinary_at_deadline), '
    '정정 기간 끝 순간 허용 여부(correction_at_window_end)를 각각 정하세요. '
    '정정이 이용 시작 전만(before_start), 시작 순간까지(through_start), 시작 뒤에도(also_after_start) 가능한지 고르세요. '
    '일반 취소와 예외의 적용 범위를 구분하고, 직전 코드에서 유지하거나 고친 결정의 근거를 원문 ID별 한 문장으로 적으세요.'
)


def facts():
    brief = public_brief()
    clauses = rules.notice_clauses(brief)
    amounts = public_quantities(clauses)
    if (set(clauses) != {'R1','R2','R3'} or '일반 취소 마감' not in clauses['R1']
            or '이용 시작' not in clauses['R1'] or '전' not in clauses['R1'] or '0은 시작 순간' not in brief
            or '이용이 시작되면' not in clauses['R2'] or '정정 시간' not in clauses['R3']
            or len(amounts) != 1 or amounts['T1']['source'] != 'R1'):
        raise ValueError('이 최종 검토 양식은 공개된 기본 예약 취소 안내문에만 적용할 수 있습니다.')
    return {'R1':dict(원문=clauses['R1'], 기준_입력='until_start_seconds', 공개_수량=amounts['T1']),
            'R2':dict(원문=clauses['R2'], 기준_입력='until_start_seconds', 계약의_시작_순간=0),
            'R3':dict(원문=clauses['R3'], 기준_입력='age_seconds', 기간='공개 문구에 수치 없음')}


def design():
    return dict(protocol='public-clock-signoff-v1', parent_protocol=prior.design_for(True)['protocol'], model=MODEL,
                previously_used=list(prior.PREVIOUS), new=list(prior.FRESH), arms=list(ARMS),
                fixed_calls=dict(direct=1, self_before=5, abcd_before=5, self_final=6, abcd=6),
                max_tokens_final=LIMIT, published_fields=facts(), response_schema=FORM,
                constraints='one unconditional source-only final review per arm, no grading or execution during generation',
                evaluation='seal all five snapshots across all seeds; stop inference; verify requests and grade')


def prefix_input(d, arm, draft):
    """Recover the exact preceding program and its assumptions using raw model answers alone."""
    clauses = rules.notice_clauses(public_brief())
    adapter = SourceRevisions(draft,clauses)
    plan, code = None, draft
    calls = ['draft.json']
    for role in PREFIX[arm]:
        name = f'{arm}/{role}.json'
        calls.append(name)
        if role == 'A':
            continue
        schema = rules.obj(adapter.slots) if plan is None else rules.patch_slots(adapter.slots)
        document = rules.decode(read(d/name)['text'],schema)
        if document is not None:
            plan = document if plan is None else rules.apply_edits(plan,document)[0]
            code, _ = adapter.render(plan)
    assumptions = {key:plan[key]['assumption'] for key in clauses} if plan else {}
    return code, assumptions, calls


def render(form, fields):
    cutoff = fields['R1']['공개_수량']['seconds']
    deadline = '>=' if form['ordinary_at_deadline'] else '>'
    window = form['correction_window']
    seconds = window['amount'] * UNIT_SECONDS[window['unit']]
    end = '<=' if form['correction_at_window_end'] else '<'
    correction = f'0 <= age_seconds {end} {seconds}'
    at_start = {'before_start':'False', 'through_start':f'until_start_seconds == 0 and {correction}',
                'also_after_start':correction}[form['correction_scope']]
    code = ['def allow_cancel(age_seconds, until_start_seconds) -> bool:',
            f'    if until_start_seconds {deadline} {cutoff}:  # R1', '        return True',
            '    if until_start_seconds <= 0:  # R2', f'        return {at_start}  # R3',
            f'    return {correction}  # R3']
    return '\n'.join(code)+'\n', {'R1':[2,3], 'R2':[4], 'R3':[5,6]}


def seal_seed(out, seed, index, port, replay=False):
    d = out/str(seed)
    draft = submission_text(read(d/'draft.json')['text'])
    rows = [prior.snapshot(seed,'direct',draft,['draft.json'])]
    fields = facts()
    for arm in (('serial','self') if index % 2 == 0 else ('self','serial')):
        previous, assumptions, calls = prefix_input(d,arm,draft)
        before, after = NAMES[arm]
        rows.append(prior.snapshot(seed,before,previous,calls))
        prompt = compact({'공개 명세':public_brief(), '원문 기준점':fields, '직전 최종 코드':previous,
                          '직전 단계가 기록한 가정':assumptions})+'\n'+INSTRUCTION
        system = MAIN if arm == 'self' else '당신은 최종 통합 책임자 D입니다. 공개 문구와 최종 코드의 시간 기준을 대조합니다.'
        name = arm+'/public-contract.json'
        role = arm+'-public-contract'
        if replay:
            call = read(d/name)
            prior.verify_request(call,seed,role,system,prompt,LIMIT,FORM)
            form, finish = rules.decode(call['text'],FORM), call['finish_reason']
        else:
            form, finish = prior.json_call(d/name, role, system, prompt, FORM, seed, port)
        code, locations = render(form,fields) if form else (previous,{})
        receipt = dict(state='applied' if form else 'unapplied_invalid_document', finish=finish,
                       before_sha256=digest(previous), after_sha256=digest(code), form=form, source_lines=locations)
        path=d/arm/'contract-receipt.json'
        if replay:
            if read(path) != receipt:
                raise ValueError('최종 결정 원문과 코드 반영 기록이 다릅니다.')
        else:
            save(path,receipt)
            print('fixed public-clock review',seed,arm,flush=True)
        rows.append(prior.snapshot(seed,after,code,calls+[name]))
    return rows


def prefix_files():
    return ['draft.json'] + [f'{arm}/{role}.json' for arm,roles in PREFIX.items() for role in roles]


def prepare_pipeline(out, port, shared_inputs_from=None):
    """The normal entry point makes every inference call in both phases before opening a grader."""
    with locked_output(out):
        path, spec = out/'design.json', design()
        if (path.exists() and read(path) != spec) or (not path.exists() and any(out.iterdir())):
            raise ValueError('전체 파이프라인은 새 폴더 또는 동일 설계의 폴더에서 시작하세요.')
        save(path,spec)
    source = out/'source-phase'
    prior.prepare_seal(source,port,True,shared_inputs_from)
    prepare_seal(out,port,source)


def prepare_seal(out, port, parent):
    with locked_output(out):
        spec, path = design(), out/'design.json'
        if (path.exists() and read(path) != spec) or (not path.exists() and any(out.iterdir())):
            raise ValueError('새 폴더 또는 동일한 최종 검토 설계의 폴더가 필요합니다.')
        save(path,spec)
        if (out/'submissions.json').exists():
            return
        if (out/'results.json').exists() or any(out.glob('*/*-score.json')):
            raise ValueError('채점된 폴더에서 모델을 호출할 수 없습니다.')
        if read(parent/'design.json') != prior.design_for(True):
            raise ValueError('확정된 원본 보존 방식의 실행이 필요합니다.')
        prior.verify_seal(parent,SEEDS,True)
        parent_rows = {(r['seed'],r['arm']):r for r in read(parent/'submissions.json')}
        batch, hashes = [], {}
        for index,seed in enumerate(SEEDS):
            for name in prefix_files():
                rel = f'{seed}/{name}'
                raw = read(parent/rel)
                dest = out/rel
                if dest.exists() and read(dest) != raw:
                    raise ValueError(f'공통 호출 원문이 기존 기록과 다릅니다: {rel}')
                dest.parent.mkdir(parents=True,exist_ok=True)
                save(dest,raw)
                hashes[rel]=digest(compact(raw))
            rows=seal_seed(out,seed,index,port)
            for row in rows:
                original_name = {'direct':'direct','self_before':'self_final','abcd_before':'abcd'}.get(row['arm'])
                if original_name and row['sha256'] != parent_rows[seed,original_name]['sha256']:
                    raise ValueError('앞 단계 원문에서 복원한 코드와 기존 고정 제출이 다릅니다.')
            batch.extend(rows)
        validate_batch(batch,SEEDS,ARMS)
        save(out/'shared-inputs.json',dict(source_protocol=spec['parent_protocol'],raw_call_hashes=hashes))
        save(out/'submissions.json',batch)


def evaluate_seal(out):
    from experiments.blind_candidates import grade_sealed
    from experiments.revision_summary import summarize
    with locked_output(out):
        if read(out/'design.json') != design():
            raise ValueError('최종 검토 설계와 제출이 일치하지 않습니다.')
        original=read(out/'submissions.json')
        validate_batch(original,SEEDS,ARMS)
        counts, replayed, hashes = Counter(), [], {}
        for index,seed in enumerate(SEEDS):
            replayed.extend(seal_seed(out,seed,index,None,replay=True))
            for name in prefix_files():
                rel = f'{seed}/{name}'
                hashes[rel]=digest(compact(read(out/rel)))
            for arm in PREFIX:
                counts[read(out/str(seed)/arm/'contract-receipt.json')['state']] += 1
        if (original != replayed or read(out/'shared-inputs.json') !=
                dict(source_protocol=design()['parent_protocol'],raw_call_hashes=hashes)):
            raise ValueError('고정한 원문과 재구성한 전체 제출이 다릅니다.')
        save(out/'integrity.json',dict(counts, shared_raw_calls=len(hashes), submissions=len(original)))
        grade_sealed(out,SEEDS,ARMS)
        pairs=[('direct','abcd'),('self_final','abcd'),('abcd_before','abcd'),
               ('self_before','self_final'),('direct','self_final')]
        save(out/'comparisons.json',summarize(out,pairs,include_stages=False))
