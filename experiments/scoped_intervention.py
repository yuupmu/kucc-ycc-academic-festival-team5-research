"""Each arm may learn only what its own questions elicit. Only its main model writes code."""
import ast
import re
import time
from concurrent.futures import ThreadPoolExecutor

from experiments import human_intervention as common, question_guide as guide, rule_edits as rules, source_thresholds
from experiments.blind_candidates import digest
from experiments.local_baseline import submission_text
from experiments.monitor_cycles import MODEL, compact, local_server, locked_output, read, recorded, save


PROTOCOL = 'human-intervention-v2'
GUIDED_PROTOCOL = 'human-intervention-guided-v1'
TABLE_PROTOCOL = 'human-intervention-ordered-v1'
THRESHOLD_PROTOCOL = 'human-intervention-source-thresholds-v1'
BOUND_TABLE_PROTOCOL = 'human-intervention-bound-ordered-v1'
TABLE_PROTOCOLS = (TABLE_PROTOCOL,THRESHOLD_PROTOCOL,BOUND_TABLE_PROTOCOL)
ARMS = common.ARMS
QUESTIONS = rules.array({'type':'string','maxLength':220},0,8)
LINK = rules.obj({'quote':common.TEXT, 'line':{'type':'string','maxLength':240}})
AUTHOR = rules.obj({'plan':common.TEXT,'questions':QUESTIONS,'code':{'type':'string','maxLength':6000},
                    'links':rules.array(LINK,0,12),'complete':rules.BOOL})
REVIEW = rules.obj({'questions':QUESTIONS,'needs_code_revision':rules.BOOL,'reason':common.TEXT})
GUIDED_AUTHOR = rules.obj({'plan':common.TEXT,'questions':QUESTIONS,'code':AUTHOR['properties']['code'],'complete':rules.BOOL})
GUIDED_REVIEW = rules.obj({'decisions':guide.CHOICES,**REVIEW['properties']})
TABLE_AUTHOR = rules.obj({'plan':common.TEXT,'questions':QUESTIONS,'rows':rules.array(guide.ROW,0,12),
                          'fallback':guide.FALLBACK,'complete':rules.BOOL})
WRITE = (
    '현재 결정할 수 있는 부분의 전체 Python 함수를 작성하세요. 서로 다른 사건에서 재는 시간을 혼동하지 마세요. '
    '근거가 없는 정책에 임의의 수치나 참·거짓을 부여하지 말고 그 경로에만 raise NotImplementedError를 남기세요. '
    '결과를 정하는 데 필요한 사람의 판단을 중립적인 자연어 질문으로 쓰세요. 기간이라면 기준 사건·길이·끝점, '
    '규칙이 겹치면 어느 규칙을 먼저 적용하는지 공개 문구 또는 이미 받은 답으로 결정되는지 읽으세요. '
    '담당자가 실제로 답한 모든 결정을 실행되는 조건에 반영하세요. 각 결정마다 links에 답변 원문의 짧은 연속 인용(quote)과 '
    '해당 결정을 구현한 실제 코드 한 줄(line)을 복사하세요. 주석을 근거 행으로 쓰지 마세요. '
    '여러 문장이면 마지막 문장까지 읽고, 우선하는 규칙의 return에 먼저 도달하는지, 정확히 같은 순간의 비교 기호가 '
    '근거와 맞는지 읽은 뒤 완성된 경우에만 complete를 true로 하세요. 답을 받은 사항을 다시 묻지 마세요.'
)
CHECK = (
    '코드를 직접 고치지 마세요. 과제와 담당자 답에 없는 정책을 코드가 추정했는지, 주어진 답의 단서와 코드가 '
    '일치하는지 읽으세요. 담당자가 결정해야 할 누락만 questions에 실제 전달할 자연어 문장으로 쓰세요. '
    '수치 환산 등 공개된 사실, 개발자가 직접 해결할 구현 문제는 묻지 마세요. '
    '기준 사건이 다르면 질문에서도 구분하세요. 정해지지 않은 내용을 정해졌다고 전제하지 마세요. '
    '기간의 길이와 끝 경계, 일반 원칙과 예외가 겹칠 때의 우선순위, 사건 발생 순간과 발생 이후 중 '
    '아직 결정되지 않은 것만 구체적으로 질문하세요. '
    '충분한 답이 있는데 코드가 잘못되었으면 needs_code_revision을 표시하세요. 검토 근거는 내부 기록입니다.'
)
REVISION_FOCUS = ('', '수정할 때 답변의 각 문장에서 정책을 찾아 그 문장과 정확한 코드 한 줄을 연결하세요.',
                  '이번에는 겹치는 조건에서 실제로 먼저 도달하는 return과 경계의 포함 여부를 소스만으로 다시 검토하세요.')
SYSTEM = '당신은 유일한 코드 작성자입니다. 공개 과제와 담당자가 직접 제공한 자연어만 운영 규칙의 근거로 사용하세요.'
TASK_DECISIONS = {'deadline_edge','correction_period','correction_edge','past_deadline','at_start','after_start'}
MAX_VERSIONS = 6


class IncompleteModelOutput(ValueError):
    def __init__(self, role, path):
        super().__init__(f'모델 출력 형식이 불완전합니다: {path.name}')
        self.role=role


def model_call(path, role, system, packet, instructions, schema, seed, limit, port):
    fmt = {'type':'json_schema','json_schema':{'name':'intervention','strict':True,'schema':schema}}
    call = recorded(path,role,system,compact(packet)+'\n'+instructions,seed,limit,port,fmt)
    doc = rules.decode(call['text'],schema)
    if doc is None:
        raise IncompleteModelOutput(role,path)
    return doc


def design(seed, initial, guided=False, ordered=False, strict_scope=False, thresholds=False, bind_times=False):
    ordered = ordered or thresholds or bind_times
    events = [SYSTEM,WRITE,CHECK,common.VIEWS,REVISION_FOCUS,AUTHOR,REVIEW]
    if guided or ordered:
        events += [guide.REVIEW_INSTRUCTION,guide.WRITE_INSTRUCTION,GUIDED_AUTHOR,GUIDED_REVIEW]
    if ordered:
        events += [guide.TABLE_INSTRUCTION,TABLE_AUTHOR]
    if thresholds:
        events += [source_thresholds.INSTRUCTION,source_thresholds.author_schema({},TABLE_AUTHOR)]
    protocol = TABLE_PROTOCOL if ordered else GUIDED_PROTOCOL if guided else PROTOCOL
    if thresholds:
        protocol = THRESHOLD_PROTOCOL
    elif bind_times:
        protocol = BOUND_TABLE_PROTOCOL
    spec=dict(protocol=protocol,model=MODEL,seed=seed,arms=list(ARMS),public_task=common.task_text(),
                initial_policy=initial,max_versions=MAX_VERSIONS,model_prompt_sha256=digest(compact(events)),
                author_token_limit=2200,reviewer_token_limit=850,
                information=('explicitly selected questions; main authors every predicate, order, action, fallback and citation' if ordered else
                             'explicitly selected neutral questions and free text per arm; cite answer sentences on source lines' if guided
                             else 'free-form questions per arm; only its own verbatim operator replies go to its author'),
                researcher='write-only notification for each code version; hidden outcomes cannot change model inputs or stopping')
    if strict_scope:
        spec['operator_scope']='interrogative-clause-v1'
        spec['policy_citations']='verbatim declarative policy sentences; raw operator replies retained'
    if thresholds:
        spec['time_conditions']='select a clock and literal from public or received text; compile cited equality and abstain at unresolved boundaries'
    elif bind_times:
        spec['time_conditions']='keep the ordered-table author prompt and rows; bind matching clock and seconds to source before review'
    return spec


def initialize(out,seed,policy_file,question_guide=False,ordered=False,thresholds=False,bind_times=False):
    path = out/'design.json'
    if path.is_file():
        spec = read(path)
        if (spec.get('protocol') not in (PROTOCOL,GUIDED_PROTOCOL,*TABLE_PROTOCOLS)
                or (question_guide and spec['protocol']!=GUIDED_PROTOCOL) or (ordered and spec['protocol']!=TABLE_PROTOCOL)
                or (thresholds and spec['protocol']!=THRESHOLD_PROTOCOL) or (bind_times and spec['protocol']!=BOUND_TABLE_PROTOCOL)):
            raise ValueError('다른 실험 폴더입니다.')
        initial = common.natural_text(policy_file) if policy_file else spec['initial_policy']
        if design(spec['seed'] if seed is None else seed,initial,spec['protocol']==GUIDED_PROTOCOL,spec['protocol']==TABLE_PROTOCOL,
                  'operator_scope' in spec,spec['protocol']==THRESHOLD_PROTOCOL,spec['protocol']==BOUND_TABLE_PROTOCOL) != spec:
            raise ValueError('실험 조건이 바뀌었습니다. 새로운 버전은 다른 실행 폴더에 기록하세요.')
    else:
        if any(out.iterdir()):
            raise ValueError('새 실험은 빈 폴더에 시작하세요.')
        spec = design(131 if seed is None else seed,common.natural_text(policy_file) if policy_file else '',question_guide,ordered,True,thresholds,bind_times)
        save(path,spec)
    state_file = out/'state.json'
    if not state_file.exists():
        arms = {name:dict(status='running',version=0) for name in ARMS}
        save(state_file,dict(status='running',started_at=time.time(),arms=arms,answers=[]))
    return spec,read(state_file)


def context(spec, state, arm):
    return {'공개 과제':spec['public_task'], '처음 제공된 정책':spec['initial_policy'],
            '담당자 자연어 답변':[a['text'] for a in state['answers'] if a['arm']==arm]}


def evidence_ok(links, code, texts):
    if not links or not any(texts):
        return False
    try:
        tree = ast.parse(code)
    except (SyntaxError,ValueError):
        return False
    source = code.splitlines()
    executable = {source[n.lineno-1].strip() for n in ast.walk(tree)
                  if isinstance(n,(ast.If,ast.Return,ast.Assign,ast.AnnAssign))}
    for link in links:
        quote, line = link['quote'].strip(), link['line'].strip()
        if not quote or not any(quote in t for t in texts) or line not in executable:
            return False
    return True


def sent_facts(state,arm):
    return {k for a in state['answers'] if a['arm']==arm for k in a.get('scoped_replies',{})}


def stated_facts(texts):
    """Conservative coverage check for direct Korean policy text. It never supplies an answer to a model."""
    found=set()
    for text in texts:
        for sentence in re.split(r'(?<=[.!?。])\s*|\n+',text):
            s=re.sub(r'\s+','',sentence)
            if (not s or '?' in s or re.search(r'미정|모르겠|정해지지|아직결정|추후결정|나중에결정|구체적으로말씀',s)):
                continue
            if ('24시간' in s or '일반마감' in s) and re.search(r'정확|딱|포함|같|경계|이상|초과|미만',s):
                found.add('deadline_edge')
            if re.search(r'예약|정정|유예',s) and re.search(r'(?:\d+|한|두|세|네|다섯|열|삼십|십)\s*(?:분|초|시간|일)',s):
                if '24시간' not in s or '예약후' in s or '예약생성후' in s:
                    found.add('correction_period')
            if re.search(r'정정|유예|기간|\d+분',s) and re.search(r'끝|마지막|만료|포함|이내|미만|정확히\d+분',s):
                found.add('correction_edge')
            if re.search(r'마감.{0,7}(지나|지난|지났|뒤|후)|일반.{0,12}보다.{0,6}우선',s) and re.search(r'정정|유예|예약생성후',s):
                found.add('past_deadline')
            if re.search(r'정정|유예|예외|취소할수없|모두거부',s) and '시작' in s:
                if re.search(r'순간|같|동시|시작전까지만|시작되면|시작시점|시작시각부터',s):
                    found.add('at_start')
                if re.search(r'이후|지난뒤|시작.{0,3}(?:뒤|후)|이미시작|시작전까지만|시작되면|시작시각부터',s):
                    found.add('after_start')
    return found


def question_list(proposals):
    groups = {}
    for source,questions in proposals:
        for q in questions:
            q=q.strip()
            if q:
                key=''.join(q.split()).rstrip('?？.')
                group=groups.setdefault(key,dict(question=q,sources=[]))
                if source not in group['sources']:
                    group['sources'].append(source)
    return list(groups.values())


def render_bound_rows(author, public_task, statements):
    """Resolve times on the existing author's rows using only this version's public and received text."""
    points = source_thresholds.catalogue(public_task,statements)
    names = {(point.clock,point.seconds):name for name,point in points.items()}
    sides = {'<':source_thresholds.BELOW,'<=':source_thresholds.BELOW,'>':source_thresholds.ABOVE,
             '>=':source_thresholds.ABOVE,'==':source_thresholds.EXACT}
    rows = []
    for row in author['rows']:
        tests = [dict(limit=names.get((test['input'],test['seconds']),source_thresholds.UNKNOWN),side=sides[test['op']])
                 for test in row['when']]
        rows.append({**row,'when':tests})
    return source_thresholds.render({**author,'rows':rows},points,statements)


def version(out,spec,state,arm,port,notify):
    current = state['arms'][arm]
    number = current['version']+1
    directory = common.round_path(out,number)
    calls, branch = directory/'calls', directory/arm
    calls.mkdir(parents=True,exist_ok=True)
    branch.mkdir(exist_ok=True)
    base = context(spec,state,arm)
    ordered = spec['protocol'] in TABLE_PROTOCOLS
    thresholds = spec['protocol']==THRESHOLD_PROTOCOL and number>1
    strict_scope = 'operator_scope' in spec
    guided = ordered or spec['protocol']==GUIDED_PROTOCOL
    texts = [base['처음 제공된 정책'], *base['담당자 자연어 답변']]
    raw_statements = guide.sentences(texts)
    statements = guide.citable_sentences(texts) if strict_scope else raw_statements
    packet = dict(base)
    if number>1:
        old = read(common.round_path(out,number-1)/arm/'snapshot.json')
        packet.update(자신의_직전_계획=old['plan'], 자신의_직전_코드=old['code'])
    role = 'shared-main' if number==1 else arm+'-main'
    author_instructions = WRITE+'\n'+REVISION_FOCUS[min(number-1,2)]
    author_schema = AUTHOR
    if guided and number>1:
        packet['담당자 원문 인용 번호'] = dict(enumerate(statements,1))
        author_instructions = guide.TABLE_INSTRUCTION if ordered else guide.WRITE_INSTRUCTION
        author_schema = TABLE_AUTHOR if ordered else GUIDED_AUTHOR
    points = {}
    if thresholds:
        points = source_thresholds.catalogue(spec['public_task'],statements)
        author_instructions = source_thresholds.INSTRUCTION
        author_schema = source_thresholds.author_schema(points,TABLE_AUTHOR)
    author = model_call(calls/(role+'.json'),role,SYSTEM,packet,author_instructions,
                        author_schema,spec['seed'],spec['author_token_limit'],port)
    if thresholds:
        code,links,trace = source_thresholds.render(author,points,statements)
        common.freeze(branch/'time-conditions.json',trace)
    elif spec['protocol']==BOUND_TABLE_PROTOCOL and number>1:
        code,links,trace = render_bound_rows(author,spec['public_task'],statements)
        common.freeze(branch/'time-conditions.json',trace)
    elif ordered and number>1:
        code,links = guide.render_table(author,statements)
    else:
        code = submission_text(author['code'])
        links = guide.source_links(code,statements) if guided and number>1 else author['links']
    common.freeze(branch/'snapshot.json',dict(version=number,arm=arm,code=code,sha256=digest(code),plan=author['plan'],
                                              links=links,main_complete=author['complete'],
                                              answer_batches=[a['batch'] for a in state['answers'] if a['arm']==arm]))
    notify()
    proposals, reviews = [(role,author['questions'])], []
    for idx,view in enumerate(common.VIEWS,1):
        reviewer = f'{arm}-review-{idx}'
        system = (f'당신은 독립 검토자 {idx}입니다. ' if arm=='multi' else '당신은 메인 개발자입니다. 스스로 검토하세요. ')+view
        packet = dict(base,메인의_계획=author['plan'],검토할_코드=code)
        if arm=='self' and reviews:
            packet['직전_자기검토'] = reviews.copy()
        review = model_call(calls/(reviewer+'.json'),reviewer,system,packet,
                            CHECK+'\n'+guide.REVIEW_INSTRUCTION if guided else CHECK,GUIDED_REVIEW if guided else REVIEW,
                            spec['seed'],spec['reviewer_token_limit'],port)
        reviews.append(review)
        selected = [q for q,pick in review.get('decisions',{}).items() if pick==guide.ASK]
        proposals.append((reviewer,[*selected,*review['questions']]))
    groups = question_list(proposals)
    removed = []
    if guided or strict_scope:
        removed = [g for g in groups if not guide.is_question(g['question']) or g['question'] in raw_statements]
        groups = [g for g in groups if g not in removed]
    prior_answers = [a for a in state['answers'] if a['arm']==arm]
    has_proxy = any(a['source']=='delegated_policy_card' for a in prior_answers)
    delivered = sent_facts(state,arm)
    manual = [base['처음 제공된 정책'],*[a['text'] for a in prior_answers if a['source']=='human']]
    manual_sentences = guide.sentences(manual)
    if has_proxy:
        # The citation gate uses only the receipt for information actually delivered to this arm.
        from experiments.intervention_operator import question_facts
        already = [g for g in groups if (facts:=question_facts(g['question'],ordered or strict_scope,strict_scope)) and facts <= delivered]
        groups = [g for g in groups if g not in already]
    else:
        already=[]
    if guided and number>1:
        # Use only sentences delivered to this branch, including direct answers and initial text.
        required = {v for a in prior_answers for k,v in a.get('scoped_replies',{}).items() if k in TASK_DECISIONS}
        required.update(s for s in manual_sentences if stated_facts([s]) & TASK_DECISIONS)
        quotes = {link['quote'] for link in links}
        linked = bool(links) and required <= quotes
    else:
        linked = evidence_ok(links,code,statements if strict_scope else texts)
    # Never use card facts which the arm has not elicited. Human-authored free replies use their citations and reviews.
    missing = sorted(TASK_DECISIONS-(delivered|stated_facts(manual)))
    ready = (author['complete'] and common.finishable(code) and linked and not missing
             and not any(r['needs_code_revision'] for r in reviews))
    review_record = dict(reviews=reviews,main_questions=author['questions'],already_answered=already,
                         missing_delivered_facts=missing,linked=linked,ready=ready)
    if guided or strict_scope:
        review_record['discarded_statements']=removed
    common.freeze(branch/'review.json',review_record)
    current['version']=number
    if groups:
        path=branch/'questions.json'
        issued = read(path)['issued_at'] if path.exists() else time.time()
        common.freeze(path,dict(arm=arm,batch=number,issued_at=issued,groups=groups))
    if ready and not groups:
        current['status']='completed'
    elif number>=spec['max_versions']:
        current['status']='incomplete_limit'
    else:
        current['status']='awaiting_human' if groups else 'running'
    persist(out,state)


def persist(out,state):
    statuses = [v['status'] for v in state['arms'].values()]
    if all(x=='completed' for x in statuses):
        state['status']='completed'
    elif 'running' in statuses:
        state['status']='running'
    elif 'awaiting_human' in statuses:
        state['status']='awaiting_human'
    elif 'incomplete_output' in statuses:
        state['status']='incomplete_output'
    else:
        state['status']='incomplete_limit'
    rows=[]
    for arm,info in state['arms'].items():
        if info['status']=='completed':
            branch=common.round_path(out,info['version'])/arm
            snap=read(branch/'snapshot.json')
            common.freeze(branch/'submission.json',snap)
            rows.append(snap)
    if rows and all(s in ('completed','incomplete_limit','incomplete_output') for s in statuses):
        common.freeze(out/'submissions.json',rows)
    save(out/'state.json',state)


def pending(out,state,arm):
    info=state['arms'][arm]
    return read(common.round_path(out,info['version'])/arm/'questions.json')


def reply(out,state,arm,batch,text,source,fragments=None,attribution=None):
    for old in state['answers']:
        if (old['arm'],old['batch'])==(arm,batch):
            if old['text'] != text:
                raise ValueError('이미 반영한 답변을 바꿀 수 없습니다.')
            return
    info=state['arms'][arm]
    if info['status']!='awaiting_human' or info['version']!=batch:
        raise ValueError('해당 방식에서 현재 기다리는 질문 번호를 확인하세요.')
    row=pending(out,state,arm)
    now=time.time()
    state['answers'].append(dict(arm=arm,batch=batch,questions=[g['question'] for g in row['groups']],
                                 source=source,text=text,scoped_replies=fragments or {},
                                 sources_by_question=attribution or {},received_at=now,wait_seconds=max(0,now-row['issued_at'])))
    info['status']='running'
    persist(out,state)


def pair_draft(out,spec,original):
    origin=read(original/'design.json')
    if origin['protocol'] not in (PROTOCOL,*TABLE_PROTOCOLS) or any(origin[k]!=spec[k] for k in ('seed','model','public_task','initial_policy')):
        raise ValueError('같은 모델·시드·공개 과제·초기 정보의 기준선 초안이 필요합니다.')
    relative='round-001/calls/shared-main.json'
    record=read(original/relative)
    # recorded() checks the entire request against the expected first-author invocation on use.
    if record['role']!='shared-main' or record['request']['messages'][0]['content']!=SYSTEM:
        raise ValueError('메인의 공통 초안 호출을 확인할 수 없습니다.')
    (out/relative).parent.mkdir(parents=True,exist_ok=True)
    common.freeze(out/relative,record)
    common.freeze(out/'draft-origin.json',dict(directory=str(original.resolve()),response_sha256=digest(record['text'])))


def run(out,port,seed=None,policy_file=None,reply_to=None,answer_file=None,operator_card=False,reply_arm=None,
        question_guide=False,draft_from=None,ordered=False,thresholds=False,bind_times=False):
    with locked_output(out):
        spec,state=initialize(out,seed,policy_file,question_guide,ordered,thresholds,bind_times)
        if draft_from is not None:
            pair_draft(out,spec,draft_from)
        if answer_file is not None:
            if reply_arm not in ARMS:
                raise ValueError('담당자 답변을 받을 실행을 --reply-arm self 또는 multi로 지정하세요.')
            reply(out,state,reply_arm,reply_to,common.natural_text(answer_file),'human')
        if not any(a['status']=='running' or (operator_card and a['status']=='awaiting_human')
                   for a in state['arms'].values()):
            show(out,state)
            return
        with ThreadPoolExecutor(max_workers=1) as research:
            def notify():
                research.submit(common.observe_separately,out)
            with local_server(port):
                while True:
                    progressed=False
                    for arm in ARMS:
                        info=state['arms'][arm]
                        if info['status']=='awaiting_human' and operator_card:
                            from experiments.intervention_operator import scoped_response
                            questions=[g['question'] for g in pending(out,state,arm)['groups']]
                            strict_scope='operator_scope' in spec
                            text,fragments,tags=scoped_response(questions,precise=spec['protocol'] in TABLE_PROTOCOLS or strict_scope,strict=strict_scope)
                            reply(out,state,arm,info['version'],text,'delegated_policy_card',fragments,tags)
                        if info['status']=='running':
                            try:
                                version(out,spec,state,arm,port,notify)
                            except IncompleteModelOutput as error:
                                info.update(status='incomplete_output',attempted_version=info['version']+1,failed_role=error.role)
                                persist(out,state)
                            progressed=True
                    if not progressed:
                        break
            notify()
        show(out,state)


def show(out,state):
    for arm,info in state['arms'].items():
        print(arm,'v'+str(info['version']),info['status'],flush=True)
        if info['status']=='awaiting_human':
            for row in pending(out,state,arm)['groups']:
                print('•',row['question'],flush=True)
