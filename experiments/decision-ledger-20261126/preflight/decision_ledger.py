"""Record independent decisions when questions are sent; specialize public rules from cited receipts."""
import ast
import itertools
import keyword
import re
from collections import defaultdict
from copy import deepcopy

from backend.allocation_repair import pending_sites
from backend.answer_contracts import SHORT
from backend.structured_output import array, obj
from experiments import guarded_reply as guards
from experiments import partial_reply as partial
from experiments.scoped_transfer import STRING


OPEN = '미정'
KINDS = ('quantity', 'decision')
ATOMIZE = """담당자에게 보낼 실제 질문들을 읽고 각각 독립적으로 답할 수 있는 결정의 목록을 만드세요.
질문이 겹치면 합치고, 한 문장에서 값과 그 값에서 취할 행동을 함께 물었다면 둘로 나누세요. 공개 명세가 이미 정한 행동이나 코드 지적은 항목에 넣지 마세요.
각 항목에는 파이썬 변수로 쓸 영문 key, 수치 자체를 물으면 quantity, 특정 상황에서 실행할지 물으면 decision,
그 항목을 포함한 원래 질문 번호 origin, 그 한 가지를 다시 물을 한국어 의문문 question을 쓰세요. question은 담당자에게 그대로 전달됩니다.
원래 질문이 이미 한 가지면 보존하세요. 묶인 질문에서는 해당 부분만 독립된 한 문장으로 적으세요.
decision 질문은 함수가 True를 반환하는 행동을 할지 묻는 긍정형으로 쓰세요. 답변과 기본값을 미리 정하지 마세요."""

PLAN = """당신은 이 함수의 작성자입니다. 담당자에게 질문을 보내는 시점에 공개 명세가 정한 행동을 한 번 기록합니다.
순서대로 처음 참인 행이 반환됩니다. when은 입력 이름, quantity 항목의 변수명, 명세에 나온 정수, 비교 연산 및 and/or/not으로 쓴 파이썬 조건식입니다.
then은 공개 규칙이면 True/False, 담당자가 정할 행동이면 해당 decision의 변수명입니다. source는 이 행의 근거인 공개 문장 번호입니다.
수치 자체는 quantity 변수로 비교하고, 결정할 행동은 별도의 decision 변수를 반환하세요. 미확정 수치나 행동을 추측하지 마세요.
가능하면 모든 입력을 포함하세요. 명세와 질문에 근거가 없으면 행을 만들지 마세요. 이미 구현된 분기도 원래 계약대로 표현하세요."""

FACTS = """담당자 발언에서 담당자가 실제로 선언한 독립적인 사실만 추출하세요. 질문, 아직 결정하지 않았다는 말, 단순한 예시는 제외하세요.
quote에는 주어와 서술어가 모두 담긴 실제 발언 부분을 문자 그대로 복사하세요. 바꾸어 쓰거나 없는 말을 채우지 마세요.
quantity는 수치 자체가 답인 선언, decision은 어떤 상황에서 무엇을 할지 정한 선언입니다. 행동을 설명하는 문장 속 수치는 맥락일 수 있습니다.
한 발언에 여러 결정이 있으면 나누세요. 짧은 긍정·부정 회신 자체도 decision입니다. 내용이 없으면 빈 배열입니다."""

MATCH = """실제 발언 하나가 직접 답하고 있는 항목 하나를 고르세요. 주제가 다르거나 둘 중 어느 항목인지 구분되지 않으면 '해당 없음'입니다.
보내 놓은 질문은 발언의 문맥일 뿐입니다. 담당자가 말한 내용만 답으로 인정하세요. 수치가 같거나 단어가 비슷하다는 이유로 다른 정책을 닫지 마세요.
value에는 quantity이면 발언의 정수, decision이면 해당 단일 질문에 대한 긍정은 True, 부정은 False, 정할 수 없으면 미정을 적으세요."""


def checked(ask, role, prompt, packet, schema, cap, validate, calls):
    for _ in range(2):
        key, value = ask(role, prompt, packet, schema, cap)
        calls.append(key)
        try:
            if value is None:
                raise ValueError('JSON record incomplete')
            return validate(value)
        except (ValueError, SyntaxError) as exc:
            packet = dict(packet, format_feedback=str(exc))
    raise ValueError(f'{role}: two invalid records')


def parse_expr(text, names, numbers):
    expr = ast.parse(text.strip(), mode='eval').body
    allowed = (ast.Name, ast.Load, ast.Constant, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.And, ast.Or,
               ast.Not, ast.UAdd, ast.USub, *guards.OPS)
    for part in ast.walk(expr):
        if not isinstance(part, allowed) or (isinstance(part, ast.Name) and part.id not in names):
            raise ValueError('Use only the supplied variable names, comparisons, and Boolean expressions: '+text)
        if isinstance(part, ast.Constant) and not (type(part.value) is bool or type(part.value) is int and abs(part.value) in numbers):
            raise ValueError('Number not present in the source before the reply: '+text)
    return expr


def expression(node, values):
    if isinstance(node, ast.Name):
        return values.get(node.id)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp):
        v = expression(node.operand, values)
        if v is None:
            return None
        if isinstance(node.op, ast.Not):
            return not v
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.BoolOp):
        items = [expression(v, values) for v in node.values]
        is_and = isinstance(node.op, ast.And)
        if any(v is not None and bool(v) != is_and for v in items):
            return not is_and
        return None if None in items else is_and
    if isinstance(node, ast.Compare):
        terms = [expression(v, values) for v in [node.left, *node.comparators]]
        undecided = False
        for op, a, b in zip(node.ops, terms, terms[1:]):
            if a is None or b is None:
                undecided = True
            elif not guards.OPS[type(op)](a,b):
                return False
        return None if undecided else True
    raise ValueError('Unsupported decision expression')


def draft_info(code, brief):
    tree = ast.parse(code)
    functions = [n for n in tree.body if isinstance(n,ast.FunctionDef)]
    main_guard = ast.dump(ast.parse("__name__ == '__main__'",mode='eval').body)
    def ignored(n):
        return ((isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str))
                or (isinstance(n,ast.If) and not n.orelse and ast.dump(n.test)==main_guard))
    if len(functions)!=1 or any(n is not functions[0] and not ignored(n) for n in tree.body):
        raise ValueError('A single Boolean decision function is required')
    fn = functions[0]
    args = fn.args.posonlyargs + fn.args.args
    if not args or fn.args.kwonlyargs or fn.args.vararg or fn.args.kwarg or fn.decorator_list:
        raise ValueError('Unsupported signature')
    names = [a.arg for a in args]
    kinds = [a.annotation.id if isinstance(a.annotation, ast.Name) else '' for a in args]
    if len(args)==1 and (kinds==['int'] or kinds==[''] and re.search(r'정수|\binteger\b|:\s*int\b',brief,re.I)):
        mode = 'integer'
    elif len(args)<=6 and all(k=='bool' for k in kinds):
        mode = 'flags'
    else:
        raise ValueError('This writer handles one integer or up to six Boolean inputs')
    if any(isinstance(n,ast.stmt) and n is not fn and not isinstance(n,(ast.If,ast.Return,ast.Raise,ast.Pass))
           and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)) for n in ast.walk(fn)):
        raise ValueError('Unsupported draft control flow')
    return fn, names, mode


def prepare(brief, code, questions, issues, ask):
    """Run before the first owner reply. The same immutable packet can be forked."""
    _, names, mode = draft_info(code, brief)
    qmap = {f'Q{i}':q for i,q in enumerate(questions,1)}
    if not qmap:
        raise ValueError('There is no question to send')
    calls = []
    publications = partial.passages(brief, [])
    nums = {abs(int(n)) for n in re.findall(r'-?\d+',brief+'\n'+code)}
    enum = partial.choices
    def validate_slots(answer):
        slots = {s['key']:s for s in answer['slots']}
        if len(slots)!=len(answer['slots']) or any(not k.isascii() or not k.isidentifier() or keyword.iskeyword(k)
                or k in names or not s['question'].strip() for k,s in slots.items()):
            raise ValueError('Use distinct English variable names and a nonempty single question')
        return slots
    options = obj(dict(key=STRING, kind=enum(KINDS), origin=enum(qmap), question=STRING))
    slots = checked(ask,'decision-items',ATOMIZE,dict(brief=brief, sent_questions=qmap),
                    obj(dict(slots=array(options,1,12))),1000,validate_slots,calls)
    quantity = {k for k,s in slots.items() if s['kind']=='quantity'}
    choices = [k for k in slots if k not in quantity]
    def validate_rules(answer):
        used = set()
        for row in answer['rules']:
            expr = parse_expr(row['when'], set(names)|quantity, nums)
            used.update(n.id for n in ast.walk(expr) if isinstance(n,ast.Name) and n.id in quantity)
            if row['then'] in choices:
                used.add(row['then'])
        if used != set(slots):
            raise ValueError('Each asked decision must occur in the symbolic plan; missing '+str(sorted(set(slots)-used)))
        return answer['rules']
    rule = obj({'when':STRING,'then':enum(['True','False',*choices]),'source':enum(publications)})
    rules = checked(ask,'public-decision-rules',PLAN,dict(public=publications, inputs=names, decisions=slots),
                    obj({'rules':array(rule,1,16)}),1400,validate_rules,calls)
    base, reopened = reopen_flag_decisions(code,brief,rules,choices) if mode=='flags' else (code,{})
    scope = (partial.scope(brief,code,questions,issues,ask) if pending_sites(code)
             else dict(accepted=False,sites=[],findings={},calls=[]))
    calls.extend(scope['calls'])
    scope['sites'] = list(dict.fromkeys([*(scope['sites'] if scope['accepted'] else []),*reopened]))
    scope.update(accepted=bool(scope['sites']), reopened=reopened)
    return dict(brief=brief, code=code, editing_base=base, sent_questions=qmap, review=issues, scope=scope, slots=slots,
                public=publications, rules=rules, names=names, mode=mode, calls=calls)


def start(agenda):
    return dict(code=agenda['editing_base'], confirmed={}, pending=list(agenda['slots']), history=[])


def source_quote(text, proposed):
    proposed = proposed.strip()
    if not proposed or len(proposed)>len(text)*2:
        return ''
    if proposed in text:
        return proposed
    pattern = r'\s*'.join(re.escape(c) for c in proposed if not c.isspace())
    matches = list(re.finditer(pattern,text)) if pattern else []
    return matches[0].group() if len(matches)==1 else ''


def accept(agenda, state, reply, ask):
    if not isinstance(reply,str) or not reply.strip() or not state['pending']:
        raise ValueError('A natural-language answer and an outstanding ticket are required')
    slots = {k:agenda['slots'][k] for k in state['pending']}
    calls, rejected, proposed = [], [], defaultdict(list)
    schema = obj(dict(facts=array(obj(dict(quote=STRING, kind=partial.choices(KINDS))),0,16)))
    key, parsed = ask('owner-statements',FACTS,{'owner_reply':reply},schema,650)
    calls.append(key)
    for fact in (parsed or {}).get('facts',[]):
        quote, kind = source_quote(reply,fact['quote']), fact['kind']
        candidates = {k:s['question'] for k,s in slots.items() if s['kind']==kind}
        if not quote or quote not in reply or not candidates or (len(slots)>1 and SHORT.fullmatch(quote)):
            rejected.append(fact)
            continue
        schema = obj(dict(item=partial.choices([*candidates,'해당 없음']),
                          value=STRING if kind=='quantity' else partial.choices(['True','False',OPEN])))
        key, match = ask('bind-owner-statement',MATCH,dict(statement=quote, asked_items=candidates,
                         kind=kind, items_in_sent_ticket=len(slots)),schema,110)
        calls.append(key)
        if not match or match['item'] not in candidates or match['value']==OPEN:
            rejected.append(fact)
            continue
        value = match['value'].strip()
        if kind=='quantity':
            if not re.fullmatch(r'[+-]?\d+',value) or int(value) not in {
                    int(s) for s in re.findall(r'(?<![\d.])[+-]?\d+(?!\d|\.\d)',quote)}:
                rejected.append(fact)
                continue
            value = int(value)
        else:
            value = value=='True'
        proposed[match['item']].append(dict(value=value, quote=quote, turn=len(state['history'])+1))
    confirmed = deepcopy(state['confirmed'])
    for k, claims in proposed.items():
        if len({c['value'] for c in claims})==1:
            confirmed[k] = claims[0]
        else:
            rejected.extend(claims)
    return confirmed, dict(ticket=list(slots), reply=reply, parsed=parsed, rejected=rejected, calls=calls)


def route(body, inputs):
    for n in body:
        if isinstance(n,ast.If):
            value = expression(n.test,inputs)
            if value is None:
                raise ValueError('Unsupported or missing input in existing branch')
            target = route(n.body if value else n.orelse,inputs)
            if target is not None:
                return target
        elif isinstance(n,ast.Raise):
            return f'@pending:{n.lineno}:{n.col_offset}'
        elif isinstance(n,ast.Return):
            return f'@return:{n.lineno}:{n.col_offset}'
    return None


def reopen_flag_decisions(code,brief,rules,decision_keys):
    """For finite flags, prove a guessed literal leaf belongs exclusively to one asked policy."""
    fn,names,_ = draft_info(code,brief)
    tests = [(ast.parse(r['when'],mode='eval').body,r['then']) for r in rules]
    leaves = defaultdict(set)
    for vs in itertools.product((False,True),repeat=len(names)):
        inputs = dict(zip(names,vs))
        leaf = route(fn.body,inputs)
        if not leaf or not leaf.startswith('@return:'):
            continue
        for test,result in tests:
            match = expression(test,inputs)
            if match is not False:
                leaves[leaf].add(result if match is True else None)
            if match is True:
                break
        else:
            leaves[leaf].add(None)
    lines, reopened = code.splitlines(keepends=True), {}
    for leaf, uses in leaves.items():
        if len(uses)!=1 or not uses<=set(decision_keys):
            continue
        _,line,column = leaf.split(':')
        i = int(line)-1
        key = next(iter(uses))
        replacement, count = re.subn(r'^(\s*)return\s+(True|False)(?=[ \t]*(?:#|\r?$))',
            lambda m: m[1]+'raise NotImplementedError("'+key+'")',lines[i],count=1,flags=re.M)
        if count:
            lines[i] = replacement
            reopened[f'@pending:{line}:{column}'] = key
    return ''.join(lines), reopened


def materialize(agenda, current, confirmed):
    """Only fill still-pending statements inside the originally selected scope."""
    if not agenda['scope']['accepted']:
        return current, []
    names = agenda['names']
    bindings = {k:s['value'] for k,s in confirmed.items()}
    frozen = [(ast.parse(r['when'],mode='eval').body,r['then']) for r in agenda['rules']]
    if agenda['mode']=='integer':
        # Existing code predicates and newly bound values are the cuts. No grading inputs enter.
        evidence = dict(agenda['public'])
        evidence['bound'] = ' '.join(str(v) for v in bindings.values() if type(v) is int)+' '
        for i,(test,_) in enumerate(frozen):
            for j,node in enumerate(ast.walk(test)):
                if isinstance(node,ast.Constant) and type(node.value) is int:
                    evidence[f'code{i}.{j}'] = str(node.value)+' '
                elif isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
                    signed = expression(node,{})
                    if type(signed) is int:
                        evidence[f'signed{i}.{j}'] = str(signed)+' '
        scenarios = [(label,{names[0]:v}) for label,v in partial.cells(current,names[0],evidence)]
    else:
        scenarios = [(' and '.join(n if v else 'not '+n for n,v in zip(names,vs)),dict(zip(names,vs)))
                     for vs in itertools.product((False,True),repeat=len(names))]
    original = draft_info(agenda['editing_base'],agenda['brief'])[0].body
    active = draft_info(current,agenda['brief'])[0].body
    available = pending_sites(current)
    edits = defaultdict(list)
    decisions = []
    for label,inputs in scenarios:
        if route(original,inputs) not in agenda['scope']['sites']:
            continue
        where = route(active,inputs)
        if where not in available:
            continue
        env = dict(bindings,**inputs)
        possible = set()
        for test, result in frozen:
            v = expression(test,env)
            if v is not None:
                v=bool(v)
            if v is not False:
                possible.add({'True':True,'False':False}.get(result,bindings.get(result)))
            if v is True:
                break
        else:
            possible.add(None)
        value = next(iter(possible)) if len(possible)==1 else None
        row = dict(site=where,region=label,value=OPEN if value is None else str(value))
        edits[where].append(row)
        decisions.append(row)
    return partial.fill(current,edits), decisions


def receive(agenda, state, reply, ask):
    confirmed, record = accept(agenda,state,reply,ask)
    code, record['edits'] = materialize(agenda,state['code'],confirmed)
    pending = [k for k in agenda['slots'] if k not in confirmed]
    return dict(code=code, confirmed=confirmed, pending=pending, history=[*state['history'],record])


def questions(agenda, state):
    return [agenda['slots'][k]['question'] for k in state['pending']]
