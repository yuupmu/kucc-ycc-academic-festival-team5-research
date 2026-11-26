"""Source-only rule editing for integer-input, boolean decision functions. No evaluator calls."""
import ast
import copy
import re

from backend.structured_output import array, decode, matches, obj


INPUTS = ('age_seconds', 'until_start_seconds')
OPS = ('<', '<=', '==', '>=', '>')
DEFAULT = 'otherwise'


TEXT = {'type': 'string', 'maxLength': 160}
FIELD = {'type': 'string', 'enum': list(INPUTS)}
BOOL = {'type': 'boolean'}
TEST = obj({'input': FIELD, 'op': {'type': 'string', 'enum': list(OPS)}, 'seconds': {'type': 'integer'}})
BRANCH = obj({'when': array(TEST, 1, 4), 'allow': BOOL})
GROUP = obj({'rank': {'type': 'integer', 'minimum': 0, 'maximum': 99},
             'branches': array(BRANCH, 0, 3), 'assumption': TEXT})
INTERPRETATION = obj({'intent': TEXT, 'inputs': array(FIELD, 0, 2), 'unspecified': TEXT})


def notice_clauses(brief):
    # The task designates its customer's public notice with quotation marks.
    sources = re.findall(r'“([^”]+)”', brief)
    sentences = [s.strip() for source in sources for s in re.split(r'(?<=[.!?])\s+', source.strip()) if s.strip()]
    if not sentences:
        raise ValueError('공개 명세에서 고객 안내문을 찾을 수 없습니다.')
    return {f'R{i}': sentence for i, sentence in enumerate(sentences, 1)}


def slots(clauses):
    return {**dict.fromkeys(clauses, GROUP), DEFAULT: BOOL}


def patch_slots(fields):
    return obj({key: {'oneOf': [obj({'keep': TEXT}), obj({'set': schema, 'reason': TEXT})]}
                for key, schema in fields.items()})


def inspect_draft(code):
    """Read the original control flow, omitting comments and docstrings that can mask an empty edit."""
    try:
        tree = ast.parse(code)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'allow_cancel')
        if ast.get_docstring(fn) is not None:
            fn.body = fn.body[1:] or [ast.Pass()]
        loaded = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        return {'function': ast.unparse(fn), 'unread_parameters': [k for k in INPUTS if k not in loaded]}
    except (SyntaxError, ValueError, StopIteration):
        return {'source': code, 'note': '함수 본문을 구문 분석할 수 없음'}


def apply_edits(plan, edits):
    """Each request replaces exactly one named slot or keeps it, without regenerating the other slots."""
    if set(edits) != set(plan):
        raise ValueError('모든 항목의 처리 내역이 필요합니다.')
    updated = copy.deepcopy(plan)
    receipt = {}
    for key, op in edits.items():
        if 'keep' in op:
            receipt[key] = {'status': 'kept', 'reason': op['keep']}
            continue
        before, after = plan[key], op['set']
        updated[key] = copy.deepcopy(after)
        if before == after:
            status = 'no_change'
        elif key != DEFAULT and all(before[k] == after[k] for k in ('rank', 'branches')):
            status = 'note_only'
        else:
            status = 'rule_edit'
        receipt[key] = dict(status=status, reason=op['reason'], before=before, after=after)
    return updated, receipt


def ordered_branches(plan, clauses):
    # Stable ties follow the sentence order in the public notice.
    for key in sorted(clauses, key=lambda k: plan[k]['rank']):
        for j, branch in enumerate(plan[key]['branches'], 1):
            yield key, f'{key}.{j}', branch


def render(plan, clauses):
    # Only validated field names, operators, literal integers and booleans enter executable code.
    if not matches(plan, obj(slots(clauses))):
        raise ValueError('유효한 규칙표만 코드로 변환할 수 있습니다.')
    lines = ['def allow_cancel(age_seconds, until_start_seconds) -> bool:']
    locations = {key: [] for key in clauses}
    for key, name, branch in ordered_branches(plan, clauses):
        condition = ' and '.join(f"{t['input']} {t['op']} {t['seconds']}" for t in branch['when'])
        locations[key].append(len(lines)+1)
        lines.extend([f'    if {condition}:  # {name}', f"        return {branch['allow']}"])
    locations[DEFAULT] = [len(lines)+1]
    lines.append(f'    return {plan[DEFAULT]}')
    return '\n'.join(lines)+'\n', locations


def bounds(tests):
    box = {k: [float('-inf'), float('inf')] for k in INPUTS}
    for t in tests:
        low, high = box[t['input']]
        n, op = t['seconds'], t['op']
        if op in ('>', '>=', '=='):
            low = max(low, n + (op == '>'))
        if op in ('<', '<=', '=='):
            high = min(high, n - (op == '<'))
        box[t['input']] = [low, high]
    return box


def order_notes(pairs):
    prior = []
    notes = []
    for name, box in pairs:
        if any(lo > hi for lo,hi in box.values()):
            notes.append(f'{name}: 같은 인자에 서로 양립할 수 없는 조건이 있음.')
        else:
            for old_name, old in prior:
                if all(old[k][0] <= box[k][0] and box[k][1] <= old[k][1] for k in INPUTS):
                    notes.append(f'{name}: 조건 범위가 앞선 {old_name}에 포함됨. 앞선 return이 먼저 실행됨.')
                    break
        prior.append((name, box))
    return notes


def source_notes(plan, clauses):
    """Literal interval inclusion on first-match source; contains no labeled inputs or correctness estimates."""
    rows = list(ordered_branches(plan, clauses))
    notes = order_notes((name, bounds(branch['when'])) for _,name,branch in rows)
    used = {t['input'] for _,_,b in rows for t in b['when']}
    return {'unread_parameters': [k for k in INPUTS if k not in used], 'branch_order_notes': notes}
