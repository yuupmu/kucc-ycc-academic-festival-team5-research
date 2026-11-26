"""Replay a three-arm blind comparison using human answers and scoped source edits."""
import argparse
import hashlib
from pathlib import Path

from backend.allocation_repair import apply_edits, owner_passages, pending_sites
from backend.structured_output import obj, array
from experiments.festival_protocol import call_model, MODEL
from experiments.local_transport import read
from experiments.project_review import freeze, publish

BANK = Path(__file__).resolve().parent / 'transfer100-20261126' / 'public'
STRING = {'type':'string'}
def evidence_choices(history):
    # A single selection binds a passage to its real originating decision.
    return {f"{h['request_id']}/{key}": dict(request_id=h['request_id'], quote=line)
            for h in history for key,line in owner_passages(h).items()}


def edit_schema(choices, sites=None):
    target = {'type':'string','enum':sites} if sites else STRING
    return obj({'evidence':{'type':'string','enum':list(choices)},'before':target,'after':STRING})


def bound_edits(proposal, choices):
    return [dict(**choices[e['evidence']], before=e['before'], after=e['after']) for e in proposal['edits']]

VIEWS = ('결과를 정하는 누락된 정책', '조건 간 상호작용과 우선순위', '경계 입력과 예외')

def run(task, out, port, *, model=MODEL, arms=('self','abc'), reviewer_schedule=None,
        model_ports=None, draft_fallback=False):
    project = read(BANK / (task + '.json'))
    out.mkdir(parents=True, exist_ok=True)
    design = dict(model=model, seed=263, task=task, cycles=3, max_questions=3, project=project)
    if reviewer_schedule is not None:
        design['reviewer_schedule'] = reviewer_schedule
    freeze(out / 'design.json', design)
    def call(role, system, packet, schema, seed, selected=None):
        chosen = selected or model
        target = dict(design, model=chosen)
        endpoint = model_ports[chosen] if model_ports else port
        key, value = call_model(out, target, role, system, packet, schema, seed, 1100, endpoint)
        keys = [key]
        if value is None:
            key, value = call_model(out, target, role, system, packet, schema, seed, 1800, endpoint)
            keys.append(key)
        if value is None:
            if 'edits' in schema['properties']:
                value = {'edits':[]}
            elif 'questions' in schema['properties']:
                value = {'questions':[],'issue':''}
            elif draft_fallback and role == 'main':
                value = {'code':project['files']['solution.py']}
                freeze(out/'draft-fallback.json',{'reason':'invalid model response','calls':keys})
            else:
                raise ValueError(f'Invalid model response {key}')
        return keys, value
    key, draft = call('main', '공개된 내용으로 구현한 전체 파이썬 소스를 code에 쓰세요. 근거 있는 경로는 구현하고 미정인 경로만 raise NotImplementedError로 남기세요. 정책을 추측하지 마세요.',
                      project, obj({'code':STRING}), 263)
    original = draft['code']
    try:
        compile(original, 'solution.py', 'exec')
    except (ValueError,SyntaxError) as exc:
        if not draft_fallback:
            raise
        freeze(out/'draft-fallback.json',{'reason':type(exc).__name__,'calls':key})
        original = project['files']['solution.py']
    publish(out, 'solo', {'solution.py':original})
    freeze(out / 'solo.json', {'calls':key})
    pending = []
    for arm in arms:
        calls, history, source = key.copy(), [], original
        for cycle in range(1,4):
            label = f'{arm}-{cycle}'
            packet = dict(brief=project['brief'], code=source, dialogue=history)
            questions, issues = [], []
            views = ('전체 정책, 경계, 상호작용',) if arm=='self' else VIEWS
            for i, view in enumerate(views):
                role = 'main-review' if arm=='self' else 'observer-'+'ABC'[i]
                identity = '당신은 작성자입니다.' if arm=='self' else '당신은 독립 감시자입니다.'
                k, result = call(role, identity + ' '+view+'를 검사하세요. 가능한 두 정책의 결과가 갈리는 상황을 찾아 담당자에게 자연어로 물으세요. 질문이 없으면 빈 배열. 이미 확정한 요구와 코드의 불일치만 issue에 적고 없으면 빈 문자열.',
                                 packet, obj({'questions':array(STRING,0,3 if arm=='self' else 1),'issue':STRING}), 263+cycle*10+i,
                                 reviewer_schedule[cycle-1][i] if arm=='abc' and reviewer_schedule else model)
                calls.extend(k)
                questions.extend(q.strip() for q in result['questions'] if q.strip())
                if result['issue'].strip():
                    issues.append(result['issue'])
            questions = list(dict.fromkeys(questions))
            freeze(out / (label+'-questions.json'), questions)
            if questions:
                reply = out / (label+'-reply.json')
                if not reply.exists():
                    pending.append(label)
                    break
                answer = read(reply)
                if not isinstance(answer,str) or not answer.strip():
                    raise ValueError('A natural-language reply is required')
                history.append(dict(request_id=label, questions=questions, answer={'text':answer}))
            if history and (questions or issues):
                choices = evidence_choices(history)
                packet.update(dialogue=history, review=issues, pending=pending_sites(source), evidence=choices)
                for retry in range(2):
                    k, proposal = call('main-edit','직접 받은 답변에 따라 코드의 필요한 위치만 수정하세요. 미구현 위치는 pending의 키를 before로 쓰고 after에 그 위치에 넣을 실행문만 적으세요. 다른 수정은 원본의 정확한 부분을 before로 인용하세요. evidence에서 근거가 되는 답변을 선택하세요. 답변으로 확정할 수 없는 동작을 만들지 마세요. 이미 맞으면 빈 edits를 반환하세요.',
                                       packet,obj({'edits':array(edit_schema(choices),0,6)}),263+cycle*10+retry)
                    calls.extend(k)
                    try:
                        source = apply_edits(source,bound_edits(proposal,choices),history,[h['request_id'] for h in history])
                        break
                    except ValueError as exc:
                        packet['edit_format_feedback'] = str(exc)
            freeze(out / (label+'-snapshot.json'),dict(code=source,calls=calls.copy(),dialogue=history.copy()))
        else:
            publish(out,arm,{'solution.py':source})
            freeze(out / (arm+'.json'),{'calls':calls})
    if pending:
        print('Awaiting natural-language replies',pending)
        return
    freeze(out/'sealed.json',{a:hashlib.sha256((out/'submissions'/a/'solution.py').read_bytes()).hexdigest()
                              for a in ('solo',*arms)})
    print('Sealed', ', '.join(('solo', *arms)), flush=True)

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('task',choices=[p.stem for p in BANK.glob('*.json')])
    parser.add_argument('out',type=Path)
    parser.add_argument('--port',type=int,default=18821)
    args=parser.parse_args()
    run(args.task,args.out,args.port)
