"""Matched local experiments with a one-shot author, self review, and independent reviewers."""
import argparse
from itertools import zip_longest
from pathlib import Path

from backend import project_review as core
from backend import project_syntax
from backend.structured_output import array, decode, obj
from experiments.local_transport import compact, local_server, locked_output, read, recorded, request_body, save
from experiments.project_review import freeze, publish


MODEL = 'var/local-models/Qwen3.5-4B-Q4_K_M.gguf'
ARMS = ('solo', 'self', 'p1', 'p2', 'p3')
DEFAULT_ARMS = ('solo', 'self', 'p2')
SLOTS = ('A', 'B', 'C')
MAX_VERSIONS = 3
QUESTION_LIMIT = 3
AUTHOR_LIMIT, REVIEW_LIMIT = 2400, 950
TERMINAL = ('one_shot', 'reviewed_complete', 'open_limit', 'invalid_output')
AUTHOR = ('당신은 이 프로젝트의 메인 개발자입니다. 공개 요구사항과 직접 받은 담당자 답변을 근거로 실제 코드를 작성하세요. '
          '초안의 동작도 요구 근거가 있는지 검토하세요. 근거가 충분한 입력에서는 가능한 결과를 구현하고, '
          '답에 따라 결과가 달라질 경로만 미결로 남기세요. 임의의 관행이나 정책값을 만들지 마세요. '
          '요구사항의 겹침과 분기 순서, 예외, 이미 확정한 동작 보존을 확인하세요. files에 지정한 각 파일의 전체 내용을 '
          '들여쓰기와 줄바꿈까지 작성하세요. 모든 요구사항을 근거 있게 구현했을 때만 complete를 참으로 하세요.')
SELF = '당신은 방금 이 파일을 작성한 메인 개발자입니다. 스스로 정보가 부족한 부분을 검사하세요.'
WATCH = '당신은 이 코드를 작성하지 않은 독립 감시자입니다.'
GENERAL = '프로젝트에서 빠진 운영 결정을 전반적으로 살피세요.'
VIEWS = ('담당자가 정할 기준 중 요구사항에서 빠진 것과 이미 정해진 것을 구별하세요.',
         '동시에 성립하는 규칙과 예외의 우선순위에 따라 결과가 달라지는지 보세요.',
         '구현이 편의상 가정한 값과 기본 동작, 이미 받은 답의 누락을 살피세요.')
CHECK = ('이미 주어진 요구사항·답변·파일을 읽고, 추가 운영 결정에 따라 결과가 달라질 때만 담당자에게 짧고 '
         '중립적인 자연어 질문을 쓰세요. 한 질문에는 판단 한 가지를 담으세요. 이미 정해진 사실과 구현 방법은 묻지 마세요. '
         'needs_code_fix는 이미 근거가 있는 내용을 코드가 잘못 구현했거나 빠뜨렸을 때만 참입니다.')
GROUNDED = (' 질문마다 해당 상황과 현재 원문이 모두 허용하는 서로 다른 결과 두 가지를 내부에 적으세요. '
            '가능한 결과가 하나로 정해지면 그 내용은 질문에서 빼세요. 담당자에게는 question만 전달됩니다.')
TEXT = {'type': 'string', 'maxLength': 350}
BOOL = {'type': 'boolean'}


def spec(project, seed, model, arms=DEFAULT_ARMS, versions=MAX_VERSIONS):
    core.validate_project(project)
    if not arms or len(set(arms)) != len(arms) or set(arms) - set(ARMS) or versions < 1:
        raise ValueError('중복되지 않는 실험 조건과 양의 버전 수가 필요합니다.')
    signature = core.digest([AUTHOR, SELF, WATCH, GENERAL, VIEWS, CHECK, GROUNDED,
                             author_schema({'file': ''}), review_schema(False), review_schema(True)])
    return dict(protocol='festival-human-review-v1', project=project, seed=seed, model=model, arms=list(arms),
                versions=versions, questions_per_window=QUESTION_LIMIT, limits=[AUTHOR_LIMIT, REVIEW_LIMIT],
                prompts_sha256=signature)


def author_schema(files):
    return obj({'files': obj({p: {'type': 'string'} for p in files}), 'complete': BOOL})


def review_schema(grounded):
    question = obj({k: TEXT for k in ('situation', 'outcome_a', 'outcome_b', 'question')}) if grounded else TEXT
    return obj({'questions': array(question, 0, QUESTION_LIMIT), 'needs_code_fix': BOOL})


def setup(out, project=None, seed=None, model=None, arms=None, versions=None):
    path = out / 'design.json'
    old = read(path) if path.exists() else {}
    if not old and any(out.iterdir()):
        raise ValueError('새 실험은 빈 폴더에서 시작하세요.')
    design = spec(project if project is not None else old.get('project'), old.get('seed', 263) if seed is None else seed,
                  model or old.get('model', MODEL), old.get('arms', DEFAULT_ARMS) if arms is None else arms,
                  old.get('versions', MAX_VERSIONS) if versions is None else versions)
    freeze(path, design)
    if not (out / 'state.json').exists():
        save(out / 'state.json', {'arms': {a: {'version': 0, 'status': 'running'} for a in design['arms']}, 'answers': []})
    return design, read(out / 'state.json')


def call_model(out, design, role, system, packet, schema, seed, limit, port, audit=False, invoke=recorded):
    fmt = {'type': 'json_schema', 'json_schema': {'name': 'project_response', 'strict': True, 'schema': schema}}
    user = compact(packet)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    request = request_body(design['model'], messages, seed, limit, 'off', fmt)
    key = core.digest([role, request])
    path = out / 'calls' / (key + '.json')
    if audit:
        raw = read(path)
    else:
        path.parent.mkdir(exist_ok=True)
        raw = invoke(path, role, system, user, seed, limit, port, fmt, design['model'])
    if (raw['role'], raw['model'], raw['request']) != (role, design['model'], request):
        raise ValueError('저장된 호출의 모델·역할·입력이 다릅니다.')
    usage = raw['usage']
    if not all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')):
        raise ValueError('실제 로컬 모델의 토큰 계측값이 없습니다.')
    if usage['total_tokens'] != usage['prompt_tokens'] + usage['completion_tokens']:
        raise ValueError('토큰 합계가 다릅니다.')
    data = decode(raw['text'], schema) if raw['finish_reason'] == 'stop' else None
    return key, data


def text_key(value):
    return ''.join(value.casefold().split()).rstrip('?？.')


def replace_files(files, edits, _evidence):
    return {**files, **{edit['file']: edit['text'] for edit in edits}}


def collect_questions(reviews, evidence):
    by_key, omitted = {}, []
    rows = [document['questions'] if document else [] for _, document in reviews]
    for alternatives in zip_longest(*rows):
        for (role, _), item in zip(reviews, alternatives):
            if item is None:
                continue
            if isinstance(item, dict):
                sides = [text_key(item[k]) for k in ('outcome_a', 'outcome_b')]
                if not item['situation'].strip() or not all(sides) or sides[0] == sides[1]:
                    omitted.append({'role': role, 'item': item, 'reason': 'distinct_outcomes_missing'})
                    continue
                item = item['question']
            question = item.strip()
            if text_key(question):
                group = by_key.setdefault(text_key(question), {'question': question, 'proposed_by': []})
                if role not in group['proposed_by']:
                    group['proposed_by'].append(role)
    eligible, copied = core.original_statements(list(by_key.values()), evidence)
    return eligible[:QUESTION_LIMIT], omitted + copied + [
        {**q, 'reason': 'window_limit'} for q in eligible[QUESTION_LIMIT:]]


def record_version(out, design, arm, version, previous, answers, port, audit=False, invoke=recorded):
    project = design['project']
    files = previous['files'] if previous else project['files']
    brief = project['brief']
    facts = [a['text'] for a in answers]
    def packet(code):
        return {'공개 요구사항': brief, '담당자 답변 원문': facts, '프로젝트 파일': code}
    seed = design['seed'] + 1000 * (version - 1)
    request = {'out': out, 'design': design, 'port': port, 'audit': audit, 'invoke': invoke}
    author_call, author = call_model(role='main-author', system=AUTHOR, packet=packet(files), schema=author_schema(files),
                                     seed=seed, limit=AUTHOR_LIMIT, **request)
    calls = [author_call]
    evidence = core.sources(brief, answers)
    candidate = files
    check = None
    if author:
        edits = [dict(file=name, first=1, last=len(source.splitlines()), text=author['files'][name])
                 for name, source in files.items() if source != author['files'][name]]
        candidate, _, check, _ = project_syntax.transaction(files, edits, evidence, replace_files)
    snapshot = dict(version=version, files=candidate, sha256=core.digest(candidate), received=[a['version'] for a in answers],
                    author_call=author_call, author_complete=bool(author and author['complete']), syntax=check)
    reviews = []
    if arm != 'solo' and author:
        for i, role in enumerate(('main-self',) if arm == 'self' else SLOTS):
            grounded = arm == 'p3'
            system = (SELF if arm == 'self' else WATCH) + ' ' + (VIEWS[i] if arm in ('p2', 'p3') else GENERAL)
            key, doc = call_model(role=role, system=system + ' ' + CHECK + (GROUNDED if grounded else ''),
                                  packet=packet(candidate), schema=review_schema(grounded),
                                  seed=seed + i + 1, limit=REVIEW_LIMIT, **request)
            calls.append(key)
            reviews.append((role, doc))
    questions, withheld = collect_questions(reviews, evidence)
    clean = bool(check and not check['rejected'] and 'invalid' not in check['verified'].values())
    ready = bool(author and author['complete'] and clean and not withheld and not questions and
                 all(doc and not doc['needs_code_fix'] for _, doc in reviews))
    if author is None or any(doc is None for _, doc in reviews):
        status = 'invalid_output'
    elif arm == 'solo':
        status = 'one_shot'
    elif ready:
        status = 'reviewed_complete'
    elif version == design['versions']:
        status = 'open_limit'
    else:
        status = 'awaiting_human' if questions else 'running'
    review = dict(calls=calls, reviewers=[{'role': r, 'response': d} for r, d in reviews], questions=questions,
                  withheld=withheld, status=status)
    folder = out / arm / f'v{version}'
    if not audit:
        folder.mkdir(parents=True, exist_ok=True)
    for name, value in [('snapshot', snapshot), ('review', review)]:
        path = folder / (name + '.json')
        if audit:
            if read(path) != value:
                raise ValueError('보관한 산출물이 호출 원문에서 재현되지 않습니다.')
        else:
            freeze(path, value)
    return snapshot, review


def advance(out, design, state, arm, port, invoke=recorded):
    info = state['arms'][arm]
    if info['status'] != 'running':
        return
    n = info['version'] + 1
    previous = read(out / arm / f'v{n-1}' / 'snapshot.json') if n > 1 else None
    answers = [a for a in state['answers'] if a['arm'] == arm and a['version'] < n]
    snapshot, review = record_version(out, design, arm, n, previous, answers, port, invoke=invoke)
    if review['status'] in TERMINAL:
        publish(out, arm, snapshot['files'])
    info.update(version=n, status=review['status'])
    save(out / 'state.json', state)


def answer(out, state, arm, version, text, source='human'):
    if arm == 'solo' or arm not in state['arms'] or source not in ('human', 'delegated_policy_card'):
        raise ValueError('이 조건 또는 출처로 답변할 수 없습니다.')
    core.natural_reply(text)
    for receipt in state['answers']:
        if (receipt['arm'], receipt['version']) == (arm, version):
            if (receipt['text'], receipt['source']) != (text, source):
                raise ValueError('이미 받은 답변은 바꿀 수 없습니다.')
            return
    if state['arms'][arm] != {'version': version, 'status': 'awaiting_human'}:
        raise ValueError('현재 답변을 기다리는 회차를 확인하세요.')
    questions = read(out / arm / f'v{version}' / 'review.json')['questions']
    state['answers'].append(dict(arm=arm, version=version, source=source, questions=questions, text=text))
    state['arms'][arm]['status'] = 'running'
    save(out / 'state.json', state)


def audit(out):
    design, state = read(out / 'design.json'), read(out / 'state.json')
    if (design != spec(design['project'], design['seed'], design['model'], design['arms'], design['versions'])
            or list(state['arms']) != design['arms']):
        raise ValueError('실행 설계가 일치하지 않습니다.')
    used, receipts = set(), []
    for arm, info in state['arms'].items():
        previous, allowed, status = None, [], 'running'
        for n in range(1, info['version'] + 1):
            if status != 'running':
                raise ValueError('미응답 질문이나 종료 뒤 호출이 있습니다.')
            previous, review = record_version(out, design, arm, n, previous, allowed, 0, audit=True)
            used.update(review['calls'])
            status = review['status']
            incoming = [a for a in state['answers'] if (a['arm'], a['version']) == (arm, n)]
            if incoming:
                a = incoming[0]
                if (len(incoming) != 1 or status != 'awaiting_human' or a['questions'] != review['questions']
                        or a['source'] not in ('human', 'delegated_policy_card')):
                    raise ValueError('질문과 답변의 출처가 일치하지 않습니다.')
                core.natural_reply(a['text'])
                allowed.append(a)
                receipts.append(a)
                status = 'running'
        if status != info['status']:
            raise ValueError('상태 전이가 일치하지 않습니다.')
        if status in TERMINAL:
            target = out / 'submissions' / arm
            exported = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()}
            if exported != {p: s.encode() for p, s in previous['files'].items()}:
                raise ValueError('고정한 최종 파일이 다릅니다.')
    if len(receipts) != len(state['answers']) or used != {p.stem for p in (out / 'calls').glob('*.json')}:
        raise ValueError('연결되지 않은 호출이나 답변이 있습니다.')
    return used


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--project', type=Path)
    parser.add_argument('--seed', type=int)
    parser.add_argument('--model')
    parser.add_argument('--arms', choices=ARMS, nargs='+')
    parser.add_argument('--versions', type=int)
    parser.add_argument('--port', type=int, default=18768)
    parser.add_argument('--reply-arm', choices=ARMS[1:])
    parser.add_argument('--reply-to', type=int)
    parser.add_argument('--answer-file', type=Path)
    args = parser.parse_args()
    with locked_output(args.out):
        design, state = setup(args.out, read(args.project) if args.project else None, args.seed, args.model, args.arms, args.versions)
        if any(x is not None for x in (args.reply_arm, args.reply_to, args.answer_file)):
            if None in (args.reply_arm, args.reply_to, args.answer_file):
                parser.error('답변의 조건·회차·자연어 파일을 함께 지정하세요.')
            answer(args.out, state, args.reply_arm, args.reply_to, args.answer_file.read_text())
        if any(x['status'] == 'running' for x in state['arms'].values()):
            with local_server(args.port, design['model']):
                while any(x['status'] == 'running' for x in state['arms'].values()):
                    for arm in design['arms']:
                        advance(args.out, design, state, arm, args.port)
        for arm, info in state['arms'].items():
            print(arm, info)
            if info['status'] == 'awaiting_human':
                for q in read(args.out / arm / f"v{info['version']}" / 'review.json')['questions']:
                    print(' •', q['question'])


if __name__ == '__main__':
    main()
