"""Operator side only. Compose a natural-language reply from the approved card and the current questions."""
import re
from pathlib import Path

from experiments.question_guide import PROMPTS, is_question

CARD = Path(__file__).resolve().parents[1]/'reservation_benchmark/evaluator/HUMAN_POLICY_BASIC.md'
FORM_FACTS = dict(zip(PROMPTS,('deadline_edge','correction_period','correction_edge','past_deadline','at_start','after_start')))


def respond(groups, card=CARD):
    document = card.read_text()
    table = {cells[0]:cells[1] for line in document.splitlines() if line.startswith('|')
             for cells in [[s.strip() for s in line.strip('|').split('|')]] if len(cells)==2}
    period, edge = re.split(r'(?<=[.!?])\s+',table['정정 시간 및 마감과의 관계'],maxsplit=1)
    covered = {'deadline_edge':table['일반 마감 시각 포함 여부'], 'correction_period':period,
               'correction_edge':edge, 'start_priority':table['이용 시작과 정정 시간의 우선순위']}
    statements, receipts = [], {}
    for group in groups:
        topic, question = group['topic'], group['question']
        if topic in covered:
            reply = covered[topic]
            receipts[topic] = reply
        elif ('age_seconds' in question or '예약 생성' in question) and ('영향' in question or '기준' in question):
            reply = '예약 직후의 정정 가능 여부는 예약 생성 후 경과한 시간을 기준으로 판단합니다.'
            receipts[question] = reply
        elif '휴무' in question:
            reply = '휴무일은 없습니다.'
            receipts[question] = reply
        elif any(t in question for t in ('입력 형식','입력값의 형식','시간대 형식')):
            reply = '모든 입력은 과제에 명시한 형식을 따릅니다.'
            receipts[question] = reply
        else:
            reply = '어떤 상황에서 판정이 달라지는지 구체적으로 말씀해 주세요.'
        if reply not in statements:
            statements.append(reply)
    return '\n'.join(statements), receipts


def asked_facts(question, precise=True):
    """Select facts from the wording actually asked. A topic label on its own releases nothing."""
    if question in FORM_FACTS:
        return {FORM_FACTS[question]}
    q = re.sub(r'\s+', '', question).lower()
    hits = set()
    correction = any(x in q for x in ('정정','유예','예외','방금','예약직후'))
    deadline = any(x in q for x in ('일반취소마감','일반마감','24시간','86400','86,400'))
    boundary = re.search(r'(정확히|정확한|딱)(이용시작)?(까지|전)?24시간|(?:24시간|86400|86,400).{0,16}(포함|경계|같|일치|순간|미만|이하|이상|일때|인경우|남았을때)|일반(?:취소)?마감(?:의|시점|시각|시간)?(을?포함|경계|순간|에정확)',q)
    if deadline and boundary:
        hits.add('deadline_edge')
    elif deadline and not correction:
        hits.add('public_deadline')
    if correction:
        if any(x in q for x in ('얼마','몇분','몇초','몇시간','몇일','며칠','지속시간','시간길이','기간의길이',
                                 '구체적인시간','구체적인기간','기간은어떻','기간이어떻','기간은어디까지',
                                 '어느정도','어느기간','몇이','몇까','시간범위','얼만큼','시간제한','몇까지',
                                 '시간한도','기간이정해','기간의기준','정정시간은어떻게정','구체적으로무엇')):
            # A question about the *remaining time to start* cannot authorize a new duration after booking.
            if not (('until_start_seconds' in q or '시작까지남은' in q) and
                    not any(x in q for x in ('예약후','예약생성','예약직후','age_seconds','얼마동안','얼마나'))):
                hits.add('correction_period')
        if ('포함' in q or '정확' in q or '경계' in q or '미만' in q or '이하' in q
                or '마지막' in q or '당시' in q) and any(x in q for x in
                ('끝','종료','만료','마지막','정정마감','유예마감','정정기간','정정시간','유예기간')):
            if not (('시작시점' in q or '시작순간' in q or '시작시각' in q) and
                    not any(x in q for x in ('기간의끝','기간끝','기간의마지막','기간이끝','정확히끝','기간이만료'))):
                hits.add('correction_edge')
        if deadline and any(x in q for x in ('지나','지난','지났','마감후','우선','충돌','겹치','예외로','별도로','예외적')):
            hits.add('past_deadline')
            if any(x in q for x in ('조건은무엇','조건이어떻','있는조건','어떤상황','특정값','허용조건')):
                hits.add('correction_period')
        if any(x in q for x in ('예약시점','예약생성','age_seconds','기산','언제부터','기준시점')):
            hits.add('correction_reference')
    if correction and ('시작' in q or 'until_start_seconds' in q):
        if any(x in q for x in ('시작순간','시작시점','시작시각','시작된순간','시작되는','시작하는','시작하자','막시작',
                                 '시작할때','시작했을때','시작된경우','시작되면','==0','=0','같거나','시작했거나')):
            hits.add('at_start')
        if re.search(r'시작(?:시각|시점|시간|된|한|하고|한시각|된시각)?(?:이후|후|뒤|지났|지난)|이미(?:이용이?)?시작|until_start_seconds<0|음수',q):
            hits.add('after_start')
    elif not correction and ('시작되면' in q or '시작된뒤' in q or '시작순간' in q or '0이하' in q):
        hits.add('public_start')
    if '휴무' in q:
        hits.add('holiday')
    if '입력형식' in q or '시간대형식' in q:
        hits.add('input_format')
    if precise and correction:
        # Confirming a named duration is different from asking about one example reservation.
        if (re.search(r'(?:기간|시간|기한)(?:은|는|이|가|으로|이얼마|얼마).{0,12}\d+(?:분|초|시간)(?:인가|입니까|이맞|으로)',q)
                or ('언제까지' in q and ('기간' in q or '시간' in q))):
            if '시작까지남은' not in q:
                hits.add('correction_period')
        if re.search(r'(?:정정|유예)(?:가능)?(?:기간|시간|기한)(?:이|이정확히|이막|의)?(?:끝나[는ㄴ]?|끝난|만료되[는ㄴ]?|종료되[는ㄴ]?)(?:바로)?(?:순간|시각|시점|때)',q):
            hits.add('correction_edge')
        if re.search(r'정확히\d+(?:분|초|시간)(?:까지)?(?:도|를|을)?포함',q) and ('기간' in q or '정정' in q):
            hits.add('correction_edge')
        if ('correction_period' in hits or 'correction_edge' in hits) and not any(x in q for x in ('언제부터','기준점','기산','기준시점')):
            hits.discard('correction_reference')
    return hits


def question_facts(question, precise=True, strict=True):
    if not strict:
        return asked_facts(question,precise)
    if question in FORM_FACTS:
        return {FORM_FACTS[question]}
    # Statements in the preamble may describe several rules. Only use them to resolve a reference.
    if not is_question(question):
        return set()
    parts=re.split(r'(?<=[.!?。？])\s+|\n+',question)
    queries=[p for p in parts if is_question(p)]
    context=re.sub(r'\s+','',question)
    facts=set()
    for clause in queries:
        text=re.sub(r'\s+','',clause)
        if (re.search(r'접수|요청을받|요청이들어|신청을받',text) and re.search(r'시각|시간대|범위|입력|언제',text)
                and not re.search(r'허용|거부|거절|우선|승인|판정|정정(?:이|할수)?가능',text)):
            continue
        if 'until_start_seconds' in text and any(word in text for word in ('어떤범위','어느범위','어떤값','몇초에해당')):
            if '일반취소마감' in context and '24시간' in context and '정정' not in context:
                facts.add('public_deadline')
            elif ('정정시간' in context or '정정기간' in context) and '정정요청' not in context:
                facts.add('correction_reference')
            # An input range describing receipt of requests does not decide whether they are allowed.
            continue
        if re.search(r'(?:정정|유예).*(?:이용)?시작전(?:몇|얼마)|(?:이용)?시작전(?:몇|얼마).*(?:정정|유예)',text):
            facts.add('correction_reference')
            continue
        if re.search(r'(정정|유예)(가능)?(기간|시간)(의)?기준(?:은|이|점|시점)',text) and not re.search(r'몇|얼마|길이|시작과끝',text):
            facts.add('correction_reference')
            continue
        scoped=asked_facts(clause,precise)
        if not scoped and ('정정' in context or '유예' in context) and text.startswith(('그기간','이기간','해당기간','기간')):
            scoped=asked_facts('정정 '+clause,precise)
        if not scoped and text.startswith(('이는','이것은','이때','이값')):
            if '일반취소' in context and '정정' not in context:
                if '시작되면' in context and ('0이하' in text or '시작' in text):
                    scoped.add('public_start')
                elif '24시간' in context and '초' in text:
                    scoped.add('public_deadline')
        facts.update(scoped)
    return facts


def scoped_response(questions, card=CARD, precise=True, strict=True):
    """Operator sees only one arm's pending natural-language questions and the policy card."""
    document = card.read_text()
    table = {items[0]:items[1] for row in document.splitlines() if row.startswith('|')
             for items in [[s.strip() for s in row.strip('|').split('|')]] if len(items)==2}
    window = table['정정 시간 및 마감과의 관계']
    amount = re.search(r'예약 생성 후 (.+?)까지',window)
    if (not amount or '경우도 포함합니다' not in window or '마감이 지나도 허용' not in window
            or '같거나 이후면' not in table['이용 시작과 정정 시간의 우선순위']
            or '거부합니다' not in table['이용 시작과 정정 시간의 우선순위']):
        raise ValueError('진행자 카드가 변경되어 문장별 응답을 다시 검토해야 합니다.')
    fragments = {
        'public_deadline':'일반 취소 마감은 이용 시작 24시간 전이며, 시작까지 남은 시간으로는 86,400초입니다.',
        'public_start':'이용이 시작된 순간부터 일반 취소는 마감됩니다.',
        'deadline_edge':table['일반 마감 시각 포함 여부'],
        'correction_reference':'정정 가능 시간을 재는 기준점은 예약 생성 시각입니다.',
        'correction_period':f'정정 기간은 예약 생성 후 {amount[1]}입니다.',
        'correction_edge':'정정 기간이 정확히 끝나는 순간도 포함합니다.',
        'past_deadline':'정정 기간 안이면 일반 취소 마감이 지난 예약도 정정할 수 있습니다.',
        'at_start':'현재 시각이 이용 시작 시각과 같으면 정정 기간이 남아 있어도 거부합니다.',
        'after_start':'이용이 이미 시작된 뒤에는 정정 기간이 남아 있어도 거부합니다.',
        'holiday':'휴무일은 없습니다.', 'input_format':'모든 입력은 과제에 명시한 형식을 따릅니다.',
    }
    attribution = {q:sorted(question_facts(q,precise,strict)) for q in questions}
    selected = {k for tags in attribution.values() for k in tags}
    answers = {k:v for k,v in fragments.items() if k in selected}
    reply = list(answers.values())
    if any(not tags for tags in attribution.values()):
        reply.append('그 밖의 질문은 어떤 상황의 운영 기준을 정해야 하는지 구체적으로 말씀해 주세요.')
    return '\n'.join(reply), answers, attribution
