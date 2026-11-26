"""Compile time comparisons from the public contract and this author's verbatim policy replies."""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from experiments import question_guide as guide, rule_edits as rules
from experiments.source_revisions import KOREAN_UNITS, UNIT_SECONDS


UNKNOWN = '미확인 기준'
BELOW, ABOVE, EXACT = '작은 쪽', '큰 쪽', '같은 순간'
INSTRUCTION = (
    '당신이 우선순위, 조건의 조합, 각 행과 기본 판정을 정합니다. 먼저 plan에 겹치는 규칙의 순서와 근거를 적으세요. '
    'when에서는 실제 원문에 있는 시간 기준(limit)과 방향(side)을 고르세요. 작은 쪽과 큰 쪽은 입력값의 크기를 뜻합니다. '
    '같은 순간의 포함 여부는 그 행의 references에 적은 담당자 문장 또는 공개 문장의 명시적인 경계 표현으로 결정됩니다. '
    '기간과 그 마지막 순간을 서로 다른 문장이 정하면 두 인용 번호를 같은 행에 넣으세요. '
    '서로 다른 입력의 시간을 대신 쓰지 마세요. 필요한 기준이 없으면 미확인 기준을 쓰고 사람에게 질문하세요. '
    '여러 조건을 한 행에 쓰면 모두 참이어야 합니다. 먼저 성립하는 행이 반환되며 나머지는 fallback이 정합니다. '
    '실행기는 인용된 단위를 초로 바꾸고, 경계 근거가 부족하면 그 경계의 판정을 보류합니다. 이미 받은 정책은 다시 묻지 마세요.'
)
AMOUNT = re.compile(r'(?<![\d.,+\-])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(시간|분|초|일)')
WINDOW = re.compile(r'([가-힣]+)\s+(?:가능\s*)?(?:기간|기한|구간)')
TENTATIVE = re.compile(r'예를\s*들|예시|가정하면|잠정|미정|정하지\s*않|정해지지|단정할\s*수\s*없|알\s*수\s*없|중\s*하나|또는|가량|약\s*\d|일\s*수도\s*있')
END = re.compile(r'마지막|끝|만료')
ZERO_EVENT = re.compile(r'시작.{0,6}(?:순간|동시|과같|와같|과일치)|시작하면|시작되면|시작과동시')


@dataclass
class Limit:
    clock: str
    seconds: int
    literal: str
    sources: list = field(default_factory=list)
    topics: set = field(default_factory=set)
    edges: list = field(default_factory=list)


def durations(sentence):
    """A compound duration is one value. Commas never turn 86,400 seconds into 400."""
    group = []
    for match in AMOUNT.finditer(sentence):
        if group and sentence[group[-1].end():match.start()].strip():
            yield from duration_value(sentence,group)
            group = []
        group.append(match)
    if group:
        yield from duration_value(sentence,group)


def duration_value(sentence,matches):
    seconds = sum(Decimal(m[1].replace(',','')) * UNIT_SECONDS[KOREAN_UNITS[m[2]]] for m in matches)
    if seconds == int(seconds):
        first,last = matches[0].start(),matches[-1].end()
        yield sentence[first:last],int(seconds),first,last


def clock_point(sentence,amount,first,last):
    age = bool(re.search(r'예약\s*(?:생성|후|직후|한\s*(?:뒤|후))|age_seconds',sentence))
    start = bool(re.search(r'(?:이용\s*)?시작|until_start_seconds',sentence))
    if age == start:
        return None
    if age:
        if re.search(r'예약\s*(?:생성\s*)?전',sentence):
            return None
        return 'age_seconds',amount
    before,after = sentence[:first],sentence[last:].lstrip()
    if after.startswith(('후','뒤','이후')) or re.search(r'시작\s*(?:한\s*)?(?:후|뒤|이후)\s*$',before):
        return 'until_start_seconds',-amount
    if after.startswith(('전','앞')) or '남은' in sentence or '시작까지' in sentence or 'until_start_seconds' in sentence:
        return 'until_start_seconds',amount
    return None


def boundary_meaning(sentence):
    """Recognize explicit period-end membership and explicit decisions at one instant."""
    text = ''.join(sentence.split())
    if re.search(r'하지만|다만|경우에만|때만|에게만|에서만',text):
        return None
    ending = r'(?:합니다|됩니다|입니다|습니다|한다|된다|해요|돼요|이다)?[.!。]?$'
    if END.search(text):
        if re.search(r'(?:제외|미포함|포함하지않|포함되지않)'+ending,text):
            return 'larger'
        if re.search(r'(?:포함|제외하지않|제외되지않)'+ending,text):
            return 'smaller'
    if not (END.search(text) or re.search(r'정확히|딱|같으면|같을때|같은|동시|일치|순간',text)):
        return None
    if re.search(r'(?:거부|불허|불가능|허용하지않|승인하지않)'+ending,text):
        return '거부'
    if re.search(r'(?:허용|승인)(?:합니다|한다|됩니다|해요)[.!。]?$',text):
        return '허용'
    return None


def catalogue(brief,statements):
    sources = [(0,s) for s in rules.notice_clauses(brief).values()]
    sources += list(enumerate(statements,1))
    points = {}
    if 'until_start_seconds' in brief and re.search(r'0은\s*시작\s*순간',brief):
        points['until_start_seconds',0] = Limit('until_start_seconds',0,'시작 순간',[(0,'0은 시작 순간')])
    evidence = []
    for ref,sentence in sources:
        if guide.is_question(sentence) or TENTATIVE.search(sentence):
            continue
        topics = set(WINDOW.findall(sentence))
        measures = [(key,literal) for literal,amount,first,last in durations(sentence)
                    if (key:=clock_point(sentence,amount,first,last)) is not None]
        located = {key for key,_ in measures}
        if len(located)>1:
            continue
        for key,literal in measures:
            point = points.setdefault(key,Limit(*key,literal))
            if (ref,sentence) not in point.sources:
                point.sources.append((ref,sentence))
            point.topics.update(topics)
        meaning = boundary_meaning(sentence)
        if meaning:
            evidence.append((ref,sentence,topics,located,meaning))
    # Two different amounts for the same named window require clarification.
    window_points = {}
    for key,point in points.items():
        for topic in point.topics:
            window_points.setdefault((point.clock,topic),set()).add(key)
    ambiguous = {key for group in window_points.values() if len(group)>1 for key in group}
    points = {key:point for key,point in points.items() if key not in ambiguous}
    for ref,sentence,topics,located,meaning in evidence:
        candidates = located & points.keys()
        if not candidates and ZERO_EVENT.search(''.join(sentence.split())):
            candidates = {('until_start_seconds',0)} & points.keys()
        elif not candidates and END.search(sentence):
            candidates = {key for key,point in points.items() if point.topics & topics}
        if len(candidates)==1:
            points[next(iter(candidates))].edges.append((ref,sentence,meaning))
    return {f'{p.clock} · {p.literal}':p for p in points.values()}


def author_schema(points,table_schema):
    test = rules.obj({'limit':{'type':'string','enum':[*points,UNKNOWN]},
                      'side':{'type':'string','enum':[BELOW,ABOVE,EXACT]}})
    row = rules.obj({**guide.ROW['properties'],'when':rules.array(test,1,3)})
    return rules.obj({**table_schema['properties'],'rows':rules.array(row,0,12)})


def admits_equality(meaning,side,action):
    if meaning in ('허용','거부'):
        return action==meaning if action in ('허용','거부') else None
    if side==EXACT:
        return None
    return (side==BELOW)==(meaning=='smaller')


def comparison(test,points,row):
    name,side = test['limit'],test['side']
    point = points.get(name)
    detail = dict(limit=name,side=side,equality=None)
    if point is None:
        return None,'',detail
    applicable = [edge for edge in point.edges if edge[0]==0 or edge[0] in row['references']]
    selected = {admits_equality(meaning,side,row['action']) for _,_,meaning in applicable}
    all_choices = {admits_equality(meaning,side,row['action']) for _,_,meaning in point.edges} - {None}
    at = selected.pop() if len(selected)==1 and len(all_choices)==1 else None
    detail.update(input=point.clock,seconds=point.seconds,
                  sources=[dict(ref=ref,text=text) for ref,text in point.sources],
                  boundary_sources=[dict(ref=ref,text=text,meaning=meaning) for ref,text,meaning in applicable],
                  equality=at)
    def expr(op):
        return f'{point.clock} {op} {point.seconds}'
    if side==EXACT:
        return (expr('==') if at is True else None),expr('=='),detail
    strict = '<' if side==BELOW else '>'
    certain = expr(strict+'=' if at is True else strict)
    possible = expr(strict+'=' if at is not False else strict)
    return certain,possible,detail


def render(decision,points,statements):
    lines = ['def allow_cancel(age_seconds, until_start_seconds):']
    trace = []
    for number,row in enumerate(decision['rows'],1):
        checks = [comparison(test,points,row) for test in row['when']]
        trace.extend(dict(row=number,**detail) for _,_,detail in checks)
        comment = guide.reference_comment(row['references'])
        if all(certain is not None for certain,_,_ in checks):
            condition = ' and '.join(certain for certain,_,_ in checks)
            lines.extend(['    if '+condition+':'+comment,'        '+guide.RESULTS[row['action']]])
        if any(certain!=possible for certain,possible,_ in checks):
            uncertain = [i for i,(certain,possible,_) in enumerate(checks) if certain!=possible]
            possible_terms = [possible for _,possible,_ in checks]
            if len(uncertain)==1:
                index = uncertain[0]
                detail = checks[index][2]
                if 'seconds' in detail:
                    possible_terms[index] = f"{detail['input']} == {detail['seconds']}"
            condition = ' and '.join(term for term in possible_terms if term)
            if not condition:
                lines.append('    '+guide.RESULTS['미정'])
                break
            lines.extend(['    if '+condition+':','        '+guide.RESULTS['미정']])
    else:
        default = decision['fallback']
        lines.append('    '+guide.RESULTS[default['action']]+guide.reference_comment(default['references']))
    code = '\n'.join(lines)+'\n'
    return code,guide.source_links(code,statements),trace
