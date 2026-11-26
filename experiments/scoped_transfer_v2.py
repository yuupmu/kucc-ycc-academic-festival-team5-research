"""Run the three-cycle scoped pipeline with a behavior description before each revision."""
import argparse
import hashlib
from pathlib import Path

from backend.structured_output import array, obj
from experiments import scoped_reply_writer as writer
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish
from experiments.scoped_transfer import BANK, STRING, VIEWS


DRAFT = '공개된 내용으로 구현한 전체 파이썬 소스를 code에 쓰세요. 근거 있는 경로는 구현하고 미정인 경로만 raise NotImplementedError로 남기세요. 정책을 추측하지 마세요.'
REVIEW = '를 검사하세요. 가능한 두 정책의 결과가 갈리는 상황을 찾아 담당자에게 자연어로 물으세요. 질문이 없으면 빈 배열. 이미 확정한 요구와 코드의 불일치만 issue에 적고 없으면 빈 문자열.'


def receive(out, label, text):
    if label not in {f'{arm}-{n}' for arm in ('self', 'abc') for n in range(1, 4)}:
        raise ValueError('답변할 조건과 회차를 지정하세요.')
    questions = out / (label + '-questions.json')
    if not questions.is_file() or not read(questions):
        raise ValueError('이 회차에 전달한 질문이 없습니다.')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('담당자의 자연어 회신이 필요합니다.')
    freeze(out / (label + '-reply.json'), text)


def run(project, out, port, *, model=MODEL, arms=('self', 'abc'), reviewer_schedule=None,
        model_ports=None, seed=263, transport=call_model):
    out.mkdir(parents=True, exist_ok=True)
    arms = tuple(arms)
    if not arms or len(set(arms)) != len(arms) or any(a not in ('self', 'abc') for a in arms):
        raise ValueError('자체 검토 또는 독립 감시 조건을 지정하세요.')
    design = dict(writer='scoped-behavior-v1', project=project, model=model, seed=seed, cycles=3,
                  max_questions=3, arms=list(arms), reviewer_schedule=reviewer_schedule)
    freeze(out / 'design.json', design)

    def ask(role, prompt, packet, schema, call_seed, limit, selected=model):
        endpoint = model_ports[selected] if model_ports else port
        return transport(out, dict(design, model=selected), role, prompt, packet,
                         schema, call_seed, limit, endpoint)

    def consult(role, prompt, packet, schema, call_seed, selected=model):
        keys = []
        for limit in (1100, 1800):
            key, value = ask(role, prompt, packet, schema, call_seed, limit, selected)
            keys.append(key)
            if value is not None:
                return keys, value
        return keys, None

    initial_calls, draft = consult('main', DRAFT, project, obj({'code': STRING}), seed)
    if draft is None:
        raise ValueError('초안 응답을 해석하지 못했습니다.')
    initial = draft['code']
    compile(initial, 'solution.py', 'exec')
    publish(out, 'solo', {'solution.py': initial})
    freeze(out / 'solo.json', {'calls': initial_calls})
    waiting = []
    for arm in arms:
        source, history, calls = initial, [], initial_calls.copy()
        for cycle in range(1, 4):
            label = f'{arm}-{cycle}'
            round_seed = seed + cycle * 10
            questions, issues = [], []
            packet = dict(brief=project['brief'], code=source, dialogue=history)
            solo_review = arm == 'self'
            for i, view in enumerate(('전체 정책, 경계, 상호작용',) if solo_review else VIEWS):
                role = 'main-review' if solo_review else 'observer-' + 'ABC'[i]
                identity = '당신은 작성자입니다.' if solo_review else '당신은 독립 감시자입니다.'
                selected = reviewer_schedule[cycle-1][i] if reviewer_schedule and not solo_review else model
                fmt = obj({'questions': array(STRING, 0, 3 if solo_review else 1), 'issue': STRING})
                keys, review = consult(role, identity + ' ' + view + REVIEW, packet, fmt, round_seed+i, selected)
                calls.extend(keys)
                if review is not None:
                    questions.extend(q.strip() for q in review['questions'] if q.strip())
                    if review['issue'].strip():
                        issues.append(review['issue'])
            questions = list(dict.fromkeys(questions))
            freeze(out / (label + '-questions.json'), questions)
            if questions:
                reply = out / (label + '-reply.json')
                if not reply.exists():
                    waiting.append(label)
                    break
                answer = read(reply)
                receive(out, label, answer)
                history.append(dict(request_id=label, questions=questions, answer={'text': answer}))
            if history and (questions or issues):
                source, record = writer.revise(project['brief'], source, history, issues, round_seed, ask)
                calls.extend(record['calls'])
                freeze(out / (label + '-writer.json'), record)
            freeze(out / (label + '-snapshot.json'), dict(code=source, calls=calls.copy(), dialogue=history.copy()))
        else:
            publish(out, arm, {'solution.py': source})
            freeze(out / (arm + '.json'), {'calls': calls})
    if not waiting:
        freeze(out / 'sealed.json', {a: hashlib.sha256((out / 'submissions' / a / 'solution.py').read_bytes()).hexdigest()
                                     for a in ('solo', *arms)})
    return waiting


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='공개 과제 이름 또는 공개 명세 JSON 경로')
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18955)
    parser.add_argument('--reply-to', help='self-1 또는 abc-1처럼 조건과 회차를 지정')
    parser.add_argument('--answer-file', type=Path)
    args = parser.parse_args()
    if bool(args.reply_to) != bool(args.answer_file):
        parser.error('--reply-to와 --answer-file을 함께 지정하세요.')
    path = Path(args.project)
    project = read(path if path.is_file() else BANK / (args.project + '.json'))
    with locked_output(args.out):
        if args.answer_file:
            receive(args.out, args.reply_to, args.answer_file.read_text())
        with local_server(args.port, MODEL):
            waiting = run(project, args.out, args.port)
    print('담당자 회신 대기 ' + ', '.join(waiting) if waiting else '제출 고정 완료')
