"""Retain the previous behavior and predicate writers; permit a genuinely partial partition."""
import ast
import re
from collections import defaultdict

from backend.allocation_repair import pending_sites
from backend.structured_output import obj
from experiments import guarded_reply as guards
from experiments import partial_reply as partial
from experiments.reply_pipeline import MATH_EQUALITY
from experiments.scoped_reply_writer import PLAN_PROMPT, PLAN_SCHEMA
from experiments.scoped_transfer import STRING, evidence_choices

LOCATION_NOTE = ' review는 감시자가 지적한 코드 위치입니다. 정책의 근거는 공개 명세와 담당자의 실제 회신입니다.'
OPEN = (
    '공개 명세가 담당자에게 맡긴 결정들을 실제 회신과 대조하세요. '
    '메모에는 어떤 결정을 답했고 어떤 결정을 아직 답하지 않았는지 한 문장으로 정리하세요. '
    '숫자의 값과 그 숫자에서의 행동은 별개일 수 있습니다. 묻기만 한 내용을 답으로 세지 마세요. '
    'unresolved_when에는 여전히 두 동작 모두 가능한 정수 입력만 파이썬 비교식 하나로 적으세요. '
    '명세와 회신으로 전부 결정되면 False입니다. 식에는 parameter의 이름, 정수, 비교 연산, and/or/not만 쓰세요.'
)


def predicate(text, name, points):
    try:
        expr = ast.parse(MATH_EQUALITY.sub('==', text.strip()), mode='eval').body
        guards.check_predicate(expr, name)
        for node in ast.walk(expr):
            if isinstance(node, ast.Compare):
                for value in (node.left, *node.comparators):
                    if not isinstance(value, ast.Name) and guards.term(value, name, 0) not in points:
                        return None
        return expr
    except (SyntaxError, ValueError, RecursionError):
        return None


def planned_actions(plan, name, points):
    actions = []
    for rule in plan:
        condition = predicate(rule['when'], name, points)
        if condition is None:
            continue
        text = rule['then']
        explicit = set(re.findall(r'\b(?:True|False)\b', text))
        if re.search('미정|보류|미확정|NotImplementedError', text, re.I):
            actions.append((condition, partial.UNKNOWN))
        elif len(explicit) == 1:
            actions.append((condition, explicit.pop()))
    return actions


def revise(brief, source, history, issues, locations, ask):
    sites, receipts = pending_sites(source), evidence_choices(history)
    name = guards.scalar_parameter(dict(code=source, brief=brief, pending=sites, review=[],
                                        evidence={'received': history[-1]['answer']['text']}))
    trace = dict(route='unavailable', calls=[], decisions=[], unresolved=[])
    if not name or not locations or not set(locations) <= sites.keys():
        return source, trace
    public = dict(brief=brief, dialogue=history)
    key, plan = ask('main-behavior', PLAN_PROMPT, public, PLAN_SCHEMA, 1100)
    trace['calls'].append(key)
    behavior = plan['behavior'] if plan else []
    data = dict(**public, evidence=receipts, parameter=name, behavior=behavior, code=source, pending=sites, review=issues)
    schema = obj({'true_when': STRING, 'false_when': STRING, 'evidence': partial.choices(receipts)})
    key, output = ask('main-predicates', guards.GUARDS+LOCATION_NOTE, data, schema, 1100)
    trace.update(behavior=behavior, predicates=output)
    trace['calls'].append(key)
    key, open_rule = ask('outstanding-policy', OPEN, dict(**public, parameter=name),
                         obj({'note': STRING, 'unresolved_when': STRING}), 440)
    trace['calls'].append(key)
    trace['outstanding_policy'] = open_rule
    evidence = partial.passages(brief, [r['answer']['text'] for r in history])
    regions = partial.cells(source, name, evidence)
    points = {x for expr, x in regions if expr == f'{name} == {x}'}
    yes = predicate(output['true_when'], name, points) if output else None
    no = predicate(output['false_when'], name, points) if output else None
    unanswered = predicate(open_rule['unresolved_when'], name, points) if open_rule else None
    actions = planned_actions(behavior, name, points)
    body = ast.parse(source).body[0].body
    changes = defaultdict(list)
    for expr, witness in regions:
        dest = partial.destination(body, name, witness)
        if dest is None or (dest[0]=='raise' and dest[1] not in sites):
            return source, trace
        if dest[0] != 'raise' or dest[1] not in locations:
            continue
        hints = {value for check, value in actions if guards.check_predicate(check, name, witness)}
        value = partial.UNKNOWN
        if yes is not None and no is not None and unanswered is not None and not guards.check_predicate(unanswered, name, witness):
            a, b = (guards.check_predicate(check, name, witness) for check in (yes, no))
            if a != b and (not hints or hints == {str(a)}):
                value = str(a)
        row = dict(region=expr, site=dest[1], behavior_actions=sorted(hints), value=value)
        trace['decisions'].append(row)
        changes[dest[1]].append(row)
        if value == partial.UNKNOWN:
            trace['unresolved'].append(expr)
    trace['route'] = 'request clarification' if trace['unresolved'] else 'implement'
    return partial.fill(source, changes), trace
