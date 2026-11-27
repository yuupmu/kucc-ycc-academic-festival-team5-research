"""Derive review-patch decisions from public input definitions and actual owner replies.

An interval endpoint describes membership. It acquires a return value only by joining
that membership to an owner-confirmed action in the same interval.
"""
import re
from collections import defaultdict
from decimal import Decimal

from backend import answer_contracts as evidence
from backend import decision_regions
from backend.anchored_program import ILLUSTRATION, MEASURE, UNITS, catalogue, unit_of


def _same_event(text):
    """Compare event names and their Korean case/verb endings."""
    words = re.findall(r'[a-z]+|[가-힣]+', text.casefold())
    skip = {'the', 'an', 'a', '때', '시점', '순간'}
    return tuple(re.sub(r'(?:하는|되는|된|한|을|를)$', '', word) for word in words if word not in skip)


def _ordered_axes(cells):
    def lower(part):
        match = re.fullmatch(fr'({evidence.NUMBER}) < {evidence.NAME} < {evidence.NUMBER}', part)
        if match:
            return (float(match[1]), 1)
        match = re.fullmatch(fr'{evidence.NAME} (==|<|>) ({evidence.NUMBER})', part)
        if match:
            return (float('-inf'), 0) if match[1] == '<' else (float(match[2]), int(match[1] == '>'))
        return (float('-inf'), 0)
    return evidence.numeric_axes(sorted(cells, key=lambda c: tuple(lower(p) for p in c.split(' and '))))


def _clocks(public, axes):
    """Use a clock only if its public declaration names its direction and event."""
    for sid, line in public.items():
        for axis in axes:
            label = r'(?<![A-Za-z0-9_])' + re.escape(axis)
            for kind, suffix in (
                ('elapsed', r'(?:은|는|:)\s*([^(),.]+?)부터\s*(?:현재까지\s*)?경과한\s*(?:시간|기간)'),
                ('remaining', r'(?:은|는|:)\s*([^(),.]+?)까지\s*남은\s*(?:시간|기간)'),
                ('elapsed', r'\s+(?:is|means)\s+(?:the\s+)?(?:time\s+)?elapsed\s+since\s+([^(),.;\n]+)'),
                ('remaining', r'\s+(?:is|means)\s+(?:the\s+)?(?:time\s+)?remaining\s+until\s+([^(),.;\n]+)'),
            ):
                for match in re.finditer(label + suffix, line, re.I):
                    yield kind, axis, match[1].strip(), sid


# Each period's name comes from the owner's statements.
_NAME_KO = r'(?P<name>[가-힣]+(?: [가-힣]+)*?)'
_NAME_EN = r'(?:the )?(?P<name>[a-z][a-z -]*?)'
_MEASURE = r'(?P<quantity>\d+(?:\.\d+)?\s*[\w]+?)'
_WINDOW = r'(?:기간|시간|구간)'
_SPEC = [
    ('clock', _NAME_KO + ' ' + _WINDOW + r'(?:은|는)\s*(?P<event>.+?)부터 (?:셉니다|계산합니다|시작합니다)'),
    ('duration', _NAME_KO + r' (?:가능 )?' + _WINDOW + r'(?:은|는) ' + _MEASURE + r'(?:입니다|이다)'),
    ('endpoint', _NAME_KO + ' ' + _WINDOW + r'(?:이|의)? (?:정확히 )?(?:끝나는 순간|종료 시점|끝점|마지막 순간)(?:도|을|은)? (?P<edge>포함합니다|제외합니다|포함하지 않습니다)'),
    ('inside', _NAME_KO + ' ' + _WINDOW + r' (?:안|이내|내)(?:이면|라면|에서는|인 경우) (?P<action>.+)'),
    ('clock', _NAME_EN + r' (?:period|window|interval) (?:starts|begins) (?:at|on|with) (?P<event>.+)'),
    ('duration', _NAME_EN + r' (?:period|window|interval) (?:is|lasts) ' + _MEASURE),
    ('endpoint', _NAME_EN + r' (?:period|window|interval) (?P<edge>includes|excludes) (?:its |the )?(?:end|endpoint|last instant)'),
    ('inside', r'(?:if|when) within ' + _NAME_EN + r' (?:period|window|interval),\s*(?P<action>.+)'),
]


def _interval_facts(owner):
    policies = defaultdict(lambda: defaultdict(list))
    for sid, reply in owner.items():
        text = reply.strip().rstrip('.!').strip()
        if ILLUSTRATION.search(text):
            continue
        for kind, pattern in _SPEC:
            match = re.fullmatch(pattern, text, re.I)
            if match:
                policies[match['name'].casefold()][kind].append((sid, match.groupdict()))
                break
    return policies


def _unique(entries, field):
    values = {item[field] for _, item in entries}
    return next(iter(values)) if len(values) == 1 else None


def _converted(quantity, axis):
    if not MEASURE.fullmatch(quantity):
        return None
    atoms = list(catalogue({'raw': quantity}, [axis]).values())
    return str(atoms[0]['value']) if len(atoms) == 1 else None


def _deadline(public, clock, name):
    """Find a public deadline relative to the event named by this remaining-time argument."""
    _, axis, event, clock_source = clock
    candidates = []
    for sid, line in public.items():
        for segment in re.split(r'[。!?\n“”";:：]|\.(?:\s|$)', line):
            ko = re.fullmatch(r'\s*([가-힣 ]+ 마감)(?:은|는) ' + re.escape(event) + r'\s*' +
                              _MEASURE + r'\s*전(?:입니다|이다)\s*', segment, re.I)
            en = re.fullmatch(r'\s*(?:the )?([a-z ]+ deadline) is ' + _MEASURE + r' before (?:the )?' +
                              re.escape(event) + r'\s*', segment, re.I)
            match = ko or en
            if match and set(name.casefold().split()) <= set(match[1].strip().casefold().split()):
                bound = _converted(match['quantity'], axis)
                if bound is not None:
                    candidates.append((bound, sid, clock_source, match[1].strip()))
    return candidates


def grounded_layout(parameters, sources):
    """Build a numeric partition without trusting a model's choice of input axis."""
    public = {sid:text for sid,text in sources.items() if sid.startswith('P')}
    owner = {sid:text for sid,text in sources.items() if sid.startswith('H')}
    clocks = list(_clocks(public, parameters))
    cuts = set()
    for clock in clocks:
        kind, axis, _, sid = clock
        # By definition, elapsed/remaining time at the named event is zero.
        cuts.add((axis, 0, sid))
        if kind == 'remaining':
            for bound, source, _, _ in _deadline(public, clock, ''):
                cuts.add((axis, Decimal(bound), source))
    for facts in _interval_facts(owner).values():
        event = _unique(facts['clock'], 'event')
        if not event:
            continue
        origins = {axis for kind, axis, anchor, _ in clocks
                   if kind == 'elapsed' and _same_event(anchor) == _same_event(event)}
        if len(origins) == 1:
            axis, = origins
            for sid, item in facts['duration']:
                bound = _converted(item['quantity'], axis)
                if bound is not None:
                    cuts.add((axis, Decimal(bound), sid))
    for atom in catalogue(sources, parameters).values():
        if atom['kind'] == 'quantity':
            compatible = [p for p in parameters if unit_of(p) and UNITS[unit_of(p)][0] == UNITS[atom['unit']][0]]
            if len(compatible) == 1:
                cuts.add((compatible[0], Decimal(str(atom['value'])), atom['source']))
    for sid, text in sources.items():
        if ILLUSTRATION.search(text):
            continue
        for axis in parameters:
            for match in re.finditer(r'(?<![A-Za-z0-9_])'+re.escape(axis)+r'\s*(?:==|[<>]=?)\s*('+evidence.NUMBER+r')(?![\w.])',text):
                cuts.add((axis, Decimal(match[1]), sid))
    if not cuts:
        return None
    # numeric_regions accepts one axis per source. One real source can define
    # several cuts, so each cut has a temporary key while building the layout.
    atoms, notes, refs = {}, {}, {}
    for i,(axis, value, sid) in enumerate(sorted(cuts)):
        cut = str(i)
        atoms[cut] = dict(kind='quantity', source=cut, inputs=[axis], value=value)
        notes[cut] = dict(input=axis)
        refs[cut] = sid
    layout = decision_regions.numeric_regions(parameters, sources, notes, atoms)
    if layout:
        cells, _, _ = layout
        for region in cells.values():
            region['anchors'] = list(dict.fromkeys(refs[x] for x in region['anchors']))
    return layout



def _action_scope(name, action, public, meanings, clocks, axes, cells):
    """Recognize an unconditional interval action, or an action even past a named deadline."""
    ko = re.fullmatch(r'(?P<label>(?:[가-힣]+ )*마감)(?:이|을) 지난 [가-힣]+도 (?P<action>[가-힣]+할 수 (?:있|없)습니다)', action)
    en = re.fullmatch(r'(?P<action>[a-z]+) even after (?:the )?(?P<label>[a-z ]+ deadline)', action, re.I)
    qualified = ko or en
    effect = qualified['action'] if qualified else action
    ability = re.fullmatch(r'([가-힣]+)할 수 (?:있|없)습니다', effect)
    value = evidence.stated_outcome('If inside, ' + effect, meanings)
    if value is None or (not qualified and not re.fullmatch(
            r'(?:return (?:True|False)|[a-z]+|[가-힣]+(?:합니다|입니다|할 수 (?:있|없)습니다))', effect, re.I)):
        return None
    if not qualified:
        if ability and ability[1] not in {*meanings, *name.split()}:
            return None
        return set(cells), value, []
    possible = []
    for clock in clocks:
        if clock[0] != 'remaining':
            continue
        axis = clock[1]
        for bound, sid, cid, label in _deadline(public, clock, qualified['label']):
            if ability and ability[1] not in {*meanings, *name.split(), *label.split()}:
                continue
            # Only the open interval between the deadline and its event. Equality at
            # that deadline and post-event behavior require separate evidence.
            before_event = axes[axis].get(f'{axis} > 0', set())
            past_deadline = axes[axis].get(f'{axis} < {bound}', set())
            if before_event and past_deadline:
                possible.append((before_event & past_deadline, value, [sid, cid]))
    return possible[0] if len(possible) == 1 else None


def _membership_claims(public, owner, axes, cells, meanings):
    clocks = list(_clocks(public, axes))
    for name, facts in _interval_facts(owner).items():
        duration = _unique(facts['duration'], 'quantity')
        event = _unique(facts['clock'], 'event')
        if not duration or not event:
            continue
        origins = [(axis, sid) for kind, axis, raw, sid in clocks
                   if kind == 'elapsed' and _same_event(raw) == _same_event(event)]
        if len(origins) != 1:
            continue
        axis, pid = origins[0]
        end = _converted(duration, axis)
        if end is None:
            continue
        limits = axes[axis]
        inside = limits.get(f'{axis} >= 0', set()) & limits.get(f'{axis} < {end}', set())
        end_cells = limits.get(f'{axis} == {end}', set())
        edges = {f['edge'].lower() in ('포함합니다', 'includes') for _, f in facts['endpoint']}
        # A partially understood qualification could limit any covered row.
        known = {sid for rows in facts.values() for sid, _ in rows}
        qualified = any(sid not in known and name in s.casefold() and _RESTRICTION.search(s)
                        for sid, s in owner.items())
        if qualified:
            continue
        polarity_sources = [sid for sid, text in public.items() if evidence.boolean_meanings(text)]
        source_ids = [pid, facts['clock'][0][0], facts['duration'][0][0], *polarity_sources]
        scoped_actions = [(sid, _action_scope(name, s['action'], public, meanings, clocks, axes, cells))
                          for sid, s in facts['inside']]
        if any(action is None for _, action in scoped_actions):
            continue
        for sid, (covered, value, refs) in scoped_actions:
            yield inside & covered, value, [*source_ids, sid, *refs]
            if edges == {True}:
                yield end_cells & covered, value, [*source_ids, facts['endpoint'][0][0], sid, *refs]



_CHANGES = re.compile(r'이전(?:의)? (?:답|기준|규칙)|정정합니다|변경(?:합니다|됐|되었)|철회|대신|번복|종전|'
                      r'\b(?:supersed\w*|instead|correction to|override\w*|revised|retract\w*)\b', re.I)
_RESTRICTION = re.compile(r'오직|단[, ]|(?:에|인 경우|때)만|제외|예외|포함하지|에 한해|'
                          r'\b(?:only|except|unless|excluding)\b', re.I)


def _collection_combinations(owner, packet, claims):
    options = packet['가능한결과']
    cells = set(packet['입력영역'])
    public = {k:v for k,v in packet['원문'].items() if k.startswith('P')}
    single = 'exactly one distinct declared value, only declared values'
    several = 'several distinct declared values, only declared values'
    single_result = 'sole declared value'
    if single not in cells or single_result not in options:
        return
    single_refs = options[single_result]['근거']
    for ref in single_refs:
        # A catalogue of names alone does not say what the interface returns for one name.
        if ref in public and re.search(r'단독으로 들어오면 같은 이름|(?:alone|on its own).{0,30}(?:same name|itself)', public[ref], re.I):
            claims[single][single_result].append(ref)

    ignore = []
    ko = (r'(?:담당|알려진|등록된|지정된|허용된) (?P<unit>[가-힣]+)[와과] '
          r'(?P<unknown>알 수 없는|미등록|등록되지 않은|알려지지 않은) (?P=unit)[이가] '
          r'(?:섞이면|함께 있으면) (?P=unknown) (?P=unit)[은는] 무시합니다')
    en = (r'(?:if|when) known and unknown (?P<unit>[a-z]+) (?:are mixed|occur together),\s*'
          r'ignore (?:the )?unknown (?P=unit)')
    for ref, text in owner.items():
        clean = text.strip().rstrip('.!')
        if re.fullmatch(ko, clean) or re.fullmatch(en, clean, re.I):
            ignore.append(ref)
    ranked_sources = {ref for refs in claims.get(several, {}).values() for ref in refs}
    for ref, text in owner.items():
        if ref in ranked_sources or ref in ignore:
            continue
        for operation in list(claims.get(several, {})):
            if not operation.startswith('first present by '):
                continue
            order = operation[len('first present by '):].split(' > ')
            destination = re.search(r'([A-Za-z][A-Za-z0-9_-]*)\s+(?:팀으로 보냅니다|팀을 선택합니다)[.! ]*$', text)
            inputs = text[:destination.start()] if destination else text
            labels = set(re.findall(r'[A-Za-z][A-Za-z0-9_-]*', inputs)).intersection(order)
            if len(labels) > 1 and (not destination or next(v for v in order if v in labels) != destination[1]):
                # Specific exceptions cannot safely be encoded in a broad "several" region.
                del claims[several][operation]
    if not ignore or any(ref not in ignore and re.search(r'알 수 없는|미등록|등록되지 않은|알려지지 않은|\bunknown\b', text, re.I)
                         for ref, text in owner.items()):
        return
    for known in (single, several):
        mixed = known.replace('only declared values', 'also undeclared values')
        if mixed in cells:
            for output, refs in claims.get(known, {}).items():
                claims[mixed][output].extend([*refs, *ignore])


def locate(description, packet):
    """Recognize a single unqualified named boundary in an issue without using its proposed result."""
    sources = packet['원문']
    cells = list(packet['입력영역'])
    axes = _ordered_axes(cells)
    if not axes or not isinstance(description, str):
        return None
    public = {k:v for k,v in sources.items() if k.startswith('P')}
    owner = {k:v for k,v in sources.items() if k.startswith('H')}
    # A general statement about the period, examples, or multiple conditions does not localize a patch.
    if _RESTRICTION.search(description) or re.search(
            r'아니면|또는|혹은|동시에|이면서|그리고|하지만|(?<![a-z])(?:and|or|if|when)(?![a-z])', description, re.I):
        return None
    mention = re.split(r'에\s*대(?:해|한|하여)|의\s*처리|에서\s*(?:오류|반환|결과|코드)|\s*[,;?!]', description.strip(), maxsplit=1)[0]
    clocks = list(_clocks(public, axes))
    found = []
    for name, facts in _interval_facts(owner).items():
        boundary = (re.escape(name) + r' (?:가능 )?' + _WINDOW +
                    r'(?:의|이|가)? (?:정확히 )?(?:끝나는 순간|종료 시점|끝점|마지막 순간)')
        other = r'(?:the )?end(?:point)? of (?:the )?' + re.escape(name) + r' (?:period|window|interval)'
        if not (re.fullmatch(boundary, mention) or re.fullmatch(other, mention, re.I)):
            continue
        event, duration = _unique(facts['clock'], 'event'), _unique(facts['duration'], 'quantity')
        if not (event and duration):
            continue
        for kind, axis, anchor, pid in clocks:
            if kind == 'elapsed' and _same_event(anchor) == _same_event(event):
                value = _converted(duration, axis)
                options = axes[axis].get(f'{axis} == {value}')
                if options:
                    found.append(options)
    direct = evidence.numeric_condition(mention, '\n'.join(public.values()), axes)
    if direct:
        found.append(direct[1])
    return found[0] if found and all(cells == found[0] for cells in found) else None


def resolve(packet, receipts, findings=()):
    """Return source-supported decisions; the editing caller intersects these with its review scope.

    Missing or conflicting decisions are absent. No candidate's proposed values
    or reviewer-suggested outcomes participate in the proof.
    """
    cells = list(packet['입력영역'])
    axes = _ordered_axes(cells)
    public = {k: v for k, v in packet['원문'].items() if k.startswith('P')}
    windows, statements = evidence.dialogue(receipts)
    by_text = {s: k for k, s in packet['원문'].items() if k.startswith('H')}
    owner = {by_text[v]: v for v in statements.values() if v in by_text}
    if any(_CHANGES.search(s) for s in owner.values()):
        # An unparsed policy amendment invalidates old interpretations. Leave it for review.
        return {}
    public_text = '\n'.join(public.values())
    meanings = evidence.boolean_meanings(public_text)
    proofs = defaultdict(lambda: defaultdict(list))
    def add(covered, value, sources):
        for cell in covered:
            proofs[cell][value].extend(sources)

    for window in windows:
        for rid in window['answers']:
            statement = statements[rid]
            sid = by_text.get(statement)
            if sid is None:
                continue
            def interpret(facts):
                text = '\n'.join(facts.values())
                return evidence.claim(statement, window['questions'], text, axes,
                                      evidence.boolean_meanings(text), packet['가능한결과'], cells, sid)
            claim = interpret(public)
            if claim is not None:
                _, covered, _, value = claim
                # Keep only public clauses actually needed to interpret this reply.
                support = public.copy()
                for ref in public:
                    reduced = {k:v for k,v in support.items() if k != ref}
                    if interpret(reduced) == claim:
                        support = reduced
                add(covered, value, [sid, *support, *packet['가능한결과'][value]['근거']])
    if axes:
        for covered, value, sources in _membership_claims(public, owner, axes, cells, meanings):
            add(covered, value, sources)
    else:
        _collection_combinations(owner, packet, proofs)
    return {cell: dict(result=next(iter(values)), sources=list(dict.fromkeys(next(iter(values.values())))))
            for cell, values in proofs.items() if len(values) == 1}

