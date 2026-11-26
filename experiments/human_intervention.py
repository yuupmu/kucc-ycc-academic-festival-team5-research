"""Local main-author / question-only reviewer comparison with real, resumable human intervention."""
import ast
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from experiments import rule_edits as rules
from experiments.blind_candidates import digest
from experiments.local_baseline import BENCHMARK, ROOT, SECONDS_CONTRACT, submission_text
from experiments.monitor_cycles import MODEL, compact, local_server, locked_output, read, recorded, save


ARMS = ('self', 'multi')
MAX_UNASSISTED = 3
# Open decisions in the public basic task. These are questions, not benchmark policy values.
TOPICS = {
    'deadline_edge':'일반 취소는 이용 시작까지 정확히 24시간 남은 순간에도 허용하나요?',
    'correction_period':'예약 직후 정정할 수 있는 기간은 예약한 뒤 얼마 동안인가요?',
    'correction_edge':'그 정정 기간이 정확히 끝나는 순간에도 정정을 허용하나요?',
    'start_priority':'정정 기간이 남아 있을 때, 이용이 막 시작된 순간과 이미 시작된 뒤에는 각각 어떻게 처리하나요?',
}
LABELS = 'deadline_edge 일반 마감 경계, correction_period 정정 기간, correction_edge 정정 끝 경계, start_priority 이용 시작과 예외의 우선순위, other 그 밖의 문제'
TEXT = {'type':'string','maxLength':400}
QUESTION = rules.obj({'topic':{'type':'string','enum':[*TOPICS,'other']}, 'question':TEXT})
QUESTIONS = rules.array(QUESTION,0,6)
AUTHOR = rules.obj({'plan':TEXT, 'questions':QUESTIONS,
                    'human_evidence':rules.obj(dict.fromkeys(TOPICS,TEXT)),
                    'code':{'type':'string','maxLength':6000}, 'complete':rules.BOOL})
REVIEW = rules.obj({'questions':QUESTIONS, 'needs_code_revision':rules.BOOL, 'reason':TEXT})
MAIN = ('당신은 이 프로젝트의 유일한 코드 작성자입니다. 공개 과제와 담당자가 직접 쓴 자연어만 운영 규칙의 근거입니다. '
        '검토자의 의견, 관행, 추측으로 정책을 정하지 마세요.')
AUTHOR_TASK = (
    '현재 결정할 수 있는 부분을 구현하고, 판정을 바꿀 정보가 빠졌으면 중립적인 질문을 남기세요. '
    '아직 정하지 못한 경로는 NotImplementedError로 명시하고 확정된 경로만 True/False를 반환하세요. '
    '이전 코드가 있으면 실제 담당자 답변을 적용해 전체 allow_cancel 함수를 제출하세요. '
    'human_evidence에는 각 미공개 정책을 확정한 담당자 문구를 그대로 짧게 인용하세요. 미확정이면 빈 문자열입니다. '
    '정정 기간과 일반 마감의 기준 시점을 구분하세요. 이미 받은 답으로 확정된 내용은 다시 묻지 마세요. '
    '상충하는 답변은 확인을 요청하세요. 모든 정책이 결정되고 코드 반영까지 끝났을 때만 complete를 true로 하세요.'
)
VIEWS = ('공개 요구와 누락된 운영 규칙을 검토합니다.', '경계 시점 및 서로 겹치는 예외를 검토합니다.',
         '코드에 임의로 넣은 정책과 담당자 답변이 실제 조건에 반영됐는지 검토합니다.')
REVIEW_TASK = (
    '같은 버전의 계획과 소스, 공개 과제와 실제 담당자 답변을 읽으세요. 정책 결정은 하지 마세요. '
    '담당자만 정할 수 있고 결과가 달라질 사항만 질문하세요. 알려진 사실이나 구현 방법은 묻지 마세요. '
    '질문에 임의의 정답 후보 수치를 넣지 마세요. 답이 불완전하면 남은 부분만 다시 물으세요. '
    '답변은 충분하지만 코드가 그 답과 어긋나거나 구현이 덜 됐으면 needs_code_revision으로 표시하세요. '
    '코드 수정은 메인의 역할입니다. 질문이 없으면 빈 목록을 쓰세요.'
)


def task_text():
    # Retain the permission to ask the operator from the original public brief.
    return SECONDS_CONTRACT+'\n\n'+(BENCHMARK/'agent/TASK_BASIC.md').read_text().split('\n\n',2)[2]


def natural_text(path):
    if any(part.endswith('-research') for part in path.resolve().parts):
        raise ValueError('연구자용 채점 기록을 모델의 정책 답변으로 지정할 수 없습니다.')
    text = path.read_text()
    if not text.strip():
        raise ValueError('빈 답변은 결정으로 등록할 수 없습니다.')
    # Prevent common score sheets / answer dumps from accidentally entering the literal human channel.
    if (text.lstrip().startswith(('{','[','```')) or re.fullmatch(r'\s*\d+\s*/\s*\d+\s*',text) or re.search(
            r'(?:가채점|채점\s*결과|테스트\s*(?:결과|통과율)|정답률|점수|score\s*[:=]|assert\s+\w+|정답\s*/\s*전체|\b\d+\s*/\s*\d+\s*(?:점|문항|정답|\|))',text,re.I)):
        raise ValueError('모델에는 운영 정책을 설명하는 자연어만 전달합니다. 채점·검사 기록은 연구자 폴더에서 확인하세요.')
    return text


def initialize(out, seed, policy_file):
    path = out/'design.json'
    if path.exists():
        spec = read(path)
        if spec.get('protocol') != 'human-intervention-v1':
            raise ValueError('다른 실험의 폴더입니다. 해당 실행 방식을 지정하거나 새 폴더를 사용하세요.')
        if seed is not None and seed != spec['seed']:
            raise ValueError('저장된 시드와 다릅니다.')
        if policy_file is not None and natural_text(policy_file) != spec['initial_policy']:
            raise ValueError('초기 정책을 바꾸려면 별도 실행 폴더를 사용하세요.')
    else:
        if any(out.iterdir()):
            raise ValueError('비어 있는 폴더에서 새 실험을 시작하세요.')
        spec = dict(protocol='human-intervention-v1', model=MODEL, seed=131 if seed is None else seed,
                    public_task=task_text(), initial_policy=natural_text(policy_file) if policy_file else '',
                    arms=list(ARMS), source_of_policy='public brief and verbatim human replies only',
                    revision_limit_per_new_answer=MAX_UNASSISTED, author_token_limit=2200, reviewer_token_limit=850,
                    comparison='shared first draft, paired human information, three equally budgeted review calls',
                    observer='separate process scores every saved version; scores never enter generation or routing')
        save(path,spec)
    state_path = out/'state.json'
    if not state_path.exists():
        save(state_path,dict(status='running',version=0,answers=[],unassisted=0))
    return spec, read(state_path)


def human_context(spec, state):
    return {'공개 과제':spec['public_task'], '담당자가 처음 제공한 정책':spec['initial_policy'],
            '담당자 문답':[{'질문':a['questions'],'답변 원문':a['text']} for a in state['answers']]}


def model_document(path, role, system, packet, instruction, schema, seed, limit, port):
    fmt = {'type':'json_schema','json_schema':{'name':'intervention','strict':True,'schema':schema}}
    prompt = compact(packet)+'\n'+instruction+'\n질문 분류: '+LABELS
    call = recorded(path,role,system,prompt,seed,limit,port,fmt)
    doc = rules.decode(call['text'],schema)
    if doc is None:
        raise ValueError(f'응답 형식을 완성하지 못해 제출을 보류했습니다: {path.name}')
    return doc


def unresolved(doc, context):
    sources = [context['담당자가 처음 제공한 정책'], *[a['답변 원문'] for a in context['담당자 문답']]]
    absent = []
    for topic, quote in doc['human_evidence'].items():
        quote = quote.strip()
        if (not quote or not any(quote in t for t in sources)
                or re.search(r'아직\s*미정|미정|모르겠|모름|추후\s*결정|정해지지|결정하지\s*않',quote)):
            absent.append(topic)
    return absent


def finishable(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError,ValueError):
        return False
    funcs = [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='allow_cancel']
    if len(funcs) != 1:
        return False
    args = funcs[0].args
    nodes = list(ast.walk(funcs[0]))
    if any(isinstance(n,ast.Pass) or (isinstance(n,ast.Constant) and n.value is Ellipsis)
           or (isinstance(n,ast.Return) and (n.value is None or isinstance(n.value,ast.Constant) and type(n.value.value) is not bool))
           or (isinstance(n,ast.Name) and n.id in ('NotImplementedError','NotImplemented')) for n in nodes):
        return False
    return ([a.arg for a in args.posonlyargs+args.args] == list(rules.INPUTS)
            and not args.kwonlyargs and not args.vararg and not args.kwarg
            and any(isinstance(n,ast.Return) for n in nodes))


def add_question(groups, topic, question, source):
    if not question.strip():
        return
    key = topic if topic in TOPICS else 'other:'+''.join(question.split())
    if key not in groups:
        groups[key] = dict(topic=topic,question=TOPICS.get(topic,question.strip()),proposals=[])
    groups[key]['proposals'].append(dict(source=source,question=question))


def round_path(out, version):
    return out/f'round-{version:03}'


def freeze(path, data):
    if path.exists():
        if read(path) != data:
            raise ValueError(f'이미 저장된 버전과 다릅니다: {path}')
    else:
        save(path,data)


def conduct_round(out, spec, state, port, notify):
    version = state['version']+1
    directory = round_path(out,version)
    calls = directory/'calls'
    calls.mkdir(parents=True,exist_ok=True)
    context = human_context(spec,state)
    groups, ready = {}, {}
    shared = None
    for arm in ARMS:
        if version == 1 and shared is not None:
            author = shared
        else:
            packet = dict(context)
            if version > 1:
                old = read(round_path(out,version-1)/arm/'snapshot.json')
                packet['자신의 직전 계획'] = old['plan']
                packet['자신의 직전 코드'] = old['code']
            role = 'shared-main' if version == 1 else arm+'-main'
            author = model_document(calls/(role+'.json'),role,MAIN,packet,AUTHOR_TASK,AUTHOR,
                                    spec['seed'],spec['author_token_limit'],port)
            shared = author
        snap_dir = directory/arm
        snap_dir.mkdir(exist_ok=True)
        code = submission_text(author['code'])
        snapshot = dict(version=version,arm=arm,code=code,sha256=digest(code),plan=author['plan'],
                        human_evidence=author['human_evidence'],main_complete=author['complete'],
                        answer_batches=[a['batch'] for a in state['answers']])
        freeze(snap_dir/'snapshot.json',snapshot)
        notify()
        for q in author['questions']:
            add_question(groups,q['topic'],q['question'],'shared-main' if version==1 else arm+'-main')
        reviews = []
        review_packet = dict(context, 메인의_계획=author['plan'], 검토할_코드=code)
        for idx, perspective in enumerate(VIEWS,1):
            role = f'{arm}-review-{idx}'
            system = (f'당신은 검토자 {idx}입니다. '+perspective if arm=='multi'
                      else '당신은 코드를 작성한 개발자입니다. 스스로 다시 검토하세요. '+perspective)
            packet = dict(review_packet)
            if arm == 'self' and reviews:
                packet['앞선 자기 검토'] = reviews.copy()
            review = model_document(calls/(role+'.json'),role,system,packet,REVIEW_TASK,REVIEW,
                                    spec['seed'],spec['reviewer_token_limit'],port)
            reviews.append(review)
            for q in review['questions']:
                add_question(groups,q['topic'],q['question'],role)
        gaps = unresolved(author,context)
        for topic in gaps:
            if topic not in groups:
                add_question(groups,topic,TOPICS[topic],'공개 과제의 미확인 항목')
        ready[arm] = (author['complete'] and not gaps and finishable(code)
                      and not any(r['needs_code_revision'] for r in reviews))
        freeze(snap_dir/'review.json',dict(reviews=reviews,missing_evidence=gaps,ready=ready[arm]))
    state['version'] = version
    state['unassisted'] += 1
    known = {k for answer in state['answers'] for k in answer.get('scoped_replies',{})}
    repeated = [k for k,g in groups.items() if (g['question'] if g['topic']=='other' else k) in known]
    if repeated:
        freeze(directory/'already-answered.json',[groups[k] for k in repeated])
        for k in repeated:
            del groups[k]
    if groups:
        question_file = directory/'questions.json'
        issued = read(question_file)['issued_at'] if question_file.exists() else time.time()
        freeze(question_file,dict(batch=version,issued_at=issued,groups=list(groups.values())))
        state['status'] = 'awaiting_human'
    elif all(ready.values()):
        submissions = [read(directory/arm/'snapshot.json') for arm in ARMS]
        freeze(out/'submissions.json',submissions)
        state['status'] = 'completed'
    elif state['unassisted'] >= spec['revision_limit_per_new_answer']:
        state['status'] = 'incomplete_review'
    else:
        state['status'] = 'running'
    save(out/'state.json',state)


def accept_answer(out, state, batch, text, source='human', scoped_replies=None):
    for prior in state['answers']:
        if prior['batch'] == batch:
            if prior['text'] != text:
                raise ValueError('이미 반영된 답변을 덮어쓸 수 없습니다.')
            return
    if state['status'] != 'awaiting_human' or state['version'] != batch:
        raise ValueError('현재 대기 중인 질문 번호에 답변하세요.')
    pending = read(round_path(out,batch)/'questions.json')
    now = time.time()
    state['answers'].append(dict(batch=batch,questions=[g['question'] for g in pending['groups']],
                                 source=source, scoped_replies=scoped_replies or {},
                                 text=text,received_at=now,wait_seconds=max(0,now-pending['issued_at'])))
    state.update(status='running',unassisted=0)
    save(out/'state.json',state)


def show(out,state):
    print(state['status'], 'v'+str(state['version']), flush=True)
    if state['status']=='awaiting_human':
        for q in read(round_path(out,state['version'])/'questions.json')['groups']:
            print('•',q['question'],flush=True)


def observe_separately(out):
    result = subprocess.run([sys.executable,'-B','-m','experiments.intervention_research',str(out.resolve())],
                            cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print('연구자용 관찰 작업 오류:',result.stderr.strip(),file=sys.stderr,flush=True)


def delegated_reply(out, state):
    from experiments.intervention_operator import respond
    batch = state['version']
    groups = read(round_path(out,batch)/'questions.json')['groups']
    text, scoped = respond(groups)
    if not scoped and any(a['text']==text and a['questions']==[g['question'] for g in groups]
                          for a in state['answers']):
        return False
    accept_answer(out,state,batch,text,'delegated_policy_card',scoped)
    return True


def run(out, port, seed=None, policy_file=None, reply_to=None, answer_file=None, operator_card=False):
    with locked_output(out):
        spec, state = initialize(out,seed,policy_file)
        if answer_file is not None:
            accept_answer(out,state,reply_to,natural_text(answer_file))
        if operator_card and state['status']=='awaiting_human':
            delegated_reply(out,state)
        if state['status']!='running':
            show(out,state)
            return
        with ThreadPoolExecutor(max_workers=1) as research:
            notify = lambda: research.submit(observe_separately,out)
            with local_server(port):
                while state['status']=='running':
                    conduct_round(out,spec,state,port,notify)
                    if operator_card and state['status']=='awaiting_human' and not delegated_reply(out,state):
                        break
            notify()
        show(out,state)
