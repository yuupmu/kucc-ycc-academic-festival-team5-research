"""Narrow corrections for owner-confirmed equality decisions on primitive inputs."""
import ast
import re
from collections import defaultdict


QUOTED = r"""(?:"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')"""
VALUE = rf'(?:{QUOTED}|-?\d{{1,16}}|True|False)'
IDENT = r'[a-zA-Z_]\w*'
TEST = rf'(?P<arg>{IDENT})\s*(?:==|(?i:is|equals)\s+|[이가은는]\s+)(?P<value>{VALUE})'
SENTENCES = (
    re.compile(rf'(?:If|When)\s+{TEST},\s*(?:return|respond with)\s+(?P<result>{VALUE})[.!]?', re.I | re.ASCII),
    re.compile(rf'{TEST}(?:이?면|일\s*때(?:에는|는)?)\s*[, ]*\s*(?P<result>{VALUE})(?:을|를)?\s*(?:반환(?:합니다|한다)|돌려줍니다)[.!]?'),
)
COORDINATE = re.compile(TEST)
AMEND = re.compile(r'^(?:correction|replacement|정정(?:합니다)?|변경(?:합니다)?)\s*[:：]\s*', re.I)
WITHDRAW = re.compile(r'철회|번복|취소합니다|종전|기존\s*(?:답변|정책).*폐기|'
                      r'\b(?:retract\w*|withdraw\w*|supersed\w*|disregard|revoke\w*)\b', re.I)


def scalar(text):
    if text.lower() in ('true', 'false'):
        return text.lower() == 'true'
    value = ast.literal_eval(text)
    if type(value) not in (str, int):
        raise ValueError('unrecognized scalar')
    return value


def predicate(arg, value):
    if type(value) is bool:
        return f'{arg} is {value}'
    # Keep Python True/1 and False/0 in different input classes.
    return f'type({arg}) is {type(value).__name__} and {arg} == {value!r}'


def locate(text, cells):
    """A stand-alone coordinate can identify a repair; an additional qualifier may change its scope."""
    phrase = text.strip().strip('().?! ')
    if phrase in cells:
        return {phrase}
    match = COORDINATE.fullmatch(phrase)
    if not match:
        return None
    try:
        key = f"{match['arg']} == {scalar(match['value'])!r}"
    except (ValueError, SyntaxError):
        return None
    return {key} if key in cells else set()


def layout(parameters, sources, receipts):
    """Return disjoint, directly witnessed guards only. Questions supply no decisions."""
    owner_ids = {text: sid for sid, text in sources.items() if sid.startswith('H')}
    outputs = {}
    cells = {}
    evidence = defaultdict(lambda: defaultdict(list))
    used_args = set()
    unresolved = set()
    for receipt in receipts:
        for sentence in receipt['text'].splitlines():
            sentence = sentence.strip()
            sid = owner_ids.get(sentence)
            if not sid:
                continue
            clause = AMEND.sub('', sentence)
            amended = clause != sentence
            for pattern in SENTENCES:
                match = pattern.fullmatch(clause)
                if match:
                    break
            else:
                located = set()
                for hit in COORDINATE.finditer(sentence):
                    try:
                        located.add(f"{hit['arg']} == {scalar(hit['value'])!r}")
                    except (SyntaxError, ValueError):
                        continue
                unresolved.update(located)
                if not located and (amended or WITHDRAW.search(sentence)):
                    unresolved.update(evidence)
                continue
            arg = match['arg']
            if arg not in parameters:
                continue
            try:
                value, result = scalar(match['value']), scalar(match['result'])
            except (SyntaxError, ValueError):
                continue
            used_args.add(arg)
            key = f'{arg} == {value!r}'
            if amended:
                evidence.pop(key, None)
                unresolved.discard(key)
            label = repr(result)
            cells[key] = dict(condition=predicate(arg, value), anchors=[])
            outputs[label] = (label, [])
            evidence[key][label].append(sid)
    if len(used_args) != 1:
        return None
    proven = {key: dict(result=next(iter(choices)), sources=list(dict.fromkeys(next(iter(choices.values())))))
              for key, choices in evidence.items() if len(choices) == 1 and key not in unresolved}
    return (cells, outputs, 'literal'), proven

