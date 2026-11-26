"""Tie explicit owner decisions to existing input regions using only the public interface and received replies."""
import ast
import re
from copy import deepcopy

from backend.anchored_program import ILLUSTRATION, catalogue


NUMBER = r'-?\d+(?:\.\d+)?'
NAME = r'[A-Za-z_][A-Za-z_0-9]*'
SHORT = re.compile(r'(네|예|맞습니다|아니요|아니오|yes|no|correct)[.! ]*', re.I)
ALTERNATIVE = re.compile(r'아니면|또는|혹은|거나|\bor\b|\bunless\b|제외|경우에만', re.I)
QUALIFIED = re.compile(r'않|아니(?:라|면|다)|아닌|아닙|못하|하지\s*말|이면서|이고\s|이며\s|그리고|경우에만|경우만|일\s*때만|'
                       r'\b(?:and|except|unless|provided|only if|not|never|might|maybe)\b', re.I)
DIRECTION = re.compile(r'직전|직후|이전|이후|부터|까지|전에|후에|이외|외에는|\b(?:after|before|since|until|except)\b', re.I)


def dialogue(receipts):
    """Keep even identical short replies attached to the particular question window that received them."""
    windows, answers = [], {}
    for rec in receipts:
        lines = [s.strip() for s in rec['text'].splitlines() if s.strip()]
        ids = [f"R{rec['cycle']}.{i}" for i in range(1, len(lines) + 1)]
        answers.update(zip(ids, lines))
        windows.append(dict(questions=[q['question'] for q in rec['questions']], answers=ids))
    return windows, answers


def boolean_meanings(public):
    meanings = {}
    patterns = [r'([가-힣]+?)(?:하면|이면|라면|일\s*때)\s*`?(True|False)(?![A-Za-z0-9_])',
                r'\b([A-Za-z][\w-]*)\s+(?:means|maps to|returns)\s+`?(True|False)\b']
    for pattern in patterns:
        for word, value in re.findall(pattern, public):
            meanings.setdefault(word.casefold(), set()).add(value)
    return {word: next(iter(vals)) for word, vals in meanings.items() if len(vals) == 1}


def boolean_result(effect, meanings):
    values = set(re.findall(r'(?<![A-Za-z0-9_])(?:True|False)(?![A-Za-z0-9_])', effect))
    if QUALIFIED.search(effect) or re.search(r'여부|인지|어떤|무엇|어떻게|미정|모르|수\s*없|\b(?:whether|which|unknown|undecided)\b', effect, re.I):
        return None
    for word, value in meanings.items():
        pattern = (r'\b' + re.escape(word) + r'\b' if word.isascii() else
                   r'(?<![가-힣])' + re.escape(word) + r'(?=\s|[.,?!]|$|으로|로|으로는|합|하|됩|처리|인가요|입니까|할까요)')
        if re.search(pattern, effect, re.I):
            values.add(value)
    return next(iter(values)) if len(values) == 1 else None


def split_condition(text):
    text = text.strip().strip('.!?').strip()
    for pattern, order in [(r'(?:if|when|at)\s+(.+?)\s*,\s*(.+)', (1, 2)),
                           (r'(.+?)\s+(?:when|if)\s+(.+)', (2, 1)),
                           (r'(.+?)(?:에는|에만|이라면|이면|라면|하면|으면|다면|인 경우(?:에는|에|는)?|일 때(?:에는|는)?)[,\s]+(.+)', (1, 2))]:
        match = re.fullmatch(pattern, text, re.I)
        if match:
            return match[order[0]], match[order[1]]
    return None, text


def numeric_axes(cells):
    parts = [c.split(' and ') for c in cells]
    axes = {}
    for column in zip(*parts):
        bands = list(dict.fromkeys(column))
        for i, band in enumerate(bands):
            match = re.fullmatch(r'(' + NAME + r') == (' + NUMBER + r')', band)
            if not match:
                continue
            name, value = match.groups()
            axis = axes.setdefault(name, {})
            for op, allowed in [('==', [band]), ('<', bands[:i]), ('<=', bands[:i+1]), ('>', bands[i+1:]), ('>=', bands[i:])]:
                axis[f'{name} {op} {value}'] = {cell for cell, actual in zip(cells, column) if actual in allowed}
    return axes


def words(text):
    return re.findall(r'[a-z]+|[가-힣]+', text.casefold())


def glossary(public, param):
    declared = re.compile(r'(?<![A-Za-z0-9_])' + re.escape(param) + r'(?:[은는]|\s*[:：]|\s+(?:is|means|denotes)\b)', re.I)
    for mark in declared.finditer(public):
        part = re.split(r'[。！？!?\n]|\.(?:\s|$)|\b' + NAME + r'(?:은|는|\s+means\b|\s+is\b|\s*[:：])', public[mark.end():], maxsplit=1)[0]
        for entry in re.finditer(r'(?<![\w.])(' + NUMBER + r')\s*(?:[은는]|means\b|denotes\b|represents\b|[:：=])\s*([^,;().\n。]+)', part, re.I):
            yield entry[1], words(entry[2]), words(part), entry[0]


def same_word(term, source):
    if term == source:
        return True
    # A Korean case particle or verbal ending can attach to a publicly declared state name.
    endings = ('이', '가', '은', '는', '을', '를', '의', '에', '에서', '되는', '하는', '한', '된')
    return not source.isascii() and any(term == source + end for end in endings)


def numeric_condition(condition, public, axes):
    condition = condition.strip().replace('`', '')
    explicit = re.fullmatch(r'(' + NAME + r')\s*(==|>=|<=|>|<)\s*(' + NUMBER + r')', condition)
    matches = {}
    if explicit:
        param, op, val = explicit.groups()
        matches[(param, op, val)] = condition
    elif re.search(r'\d', condition):
        # An explicit quantity can be converted only when the owner names the actual argument.
        for param in axes:
            atoms = [a for a in catalogue({'owner': condition}, [param]).values() if a['kind'] == 'quantity']
            if len(atoms) != 1:
                continue
            atom = atoms[0]
            item = re.escape(atom['quote'])
            arg = re.escape(param)
            for op, ko, en in [('>=', '이상', 'at least'), ('<=', '이하', 'at most'), ('>', '초과', 'more than|greater than'),
                               ('<', '미만', 'less than'), ('==', '와 같다|와 같|와 동일', 'exactly|equal to')]:
                if re.fullmatch(fr'{arg}(?:가|이|는|은)?\s+{item}\s*(?:{ko})|{arg}\s+(?:is\s+)?(?:{en})\s+{item}', condition, re.I):
                    matches[(param, op, str(atom['value']))] = atom['quote']
    elif not DIRECTION.search(condition):
        terms = [t for t in words(condition) if t not in ('the', 'a', 'an', 'at', 'of')]
        for param in axes:
            for val, alias, declared, quote in glossary(public, param):
                alias = [w for w in alias if w not in ('the', 'a', 'an', 'at', 'of')]
                # Extra qualifications such as a membership class or a weekday narrow this condition.
                if alias and all(any(same_word(t, w) for t in terms) for w in alias) and all(
                        any(same_word(t, w) for w in declared) for t in terms):
                    matches[(param, '==', val)] = quote
    if len(matches) == 1:
        (param, op, value), quote = next(iter(matches.items()))
        label = f'{param} {op} {value}'
        if label in axes.get(param, {}):
            return label, axes[param][label], quote
    return None


def collection_claim(statement, source, options, cells):
    if QUALIFIED.search(statement) or ALTERNATIVE.search(statement) or ILLUSTRATION.search(statement):
        return None
    cell = 'several distinct declared values, only declared values'
    for name, definition in options.items():
        if not name.startswith('first present by ') or source not in definition['근거'] or cell not in cells:
            continue
        ordering = r'\s*,\s*'.join(re.escape(s) for s in name.removeprefix('first present by ').split(' > '))
        if re.fullmatch(r'(?:여러\s+[가-힣 ]+?(?:있으면|겹치면)\s+' + ordering +
                        r'\s*순(?:서)?로\s*가장\s*앞선\s*[가-힣 ]*선택합니다|(?:priority order|in descending priority)\s*:\s*' +
                        ordering + r')[.! ]*', statement, re.I):
            return cell, {cell}, statement, name
    empty = re.fullmatch(r'(?:빈\s*[^\s,]+?(?:은|는|이면|일 때)|(?:if|when) (?:the )?(?:list|input|collection) is empty\s*,)\s*(.+)', statement, re.I)
    if empty and not re.search(r'(?:하면|이면|경우|\b(?:when|if|only)\b)', empty[1], re.I) and 'empty input' in cells:
        labels = [k for k in options if k.startswith('literal ') and re.search(
            r'(?<![A-Za-z0-9_-])' + re.escape(ast.literal_eval(k[len('literal '):])) + r'(?![A-Za-z0-9_-])', empty[1])]
        if len(labels) == 1:
            return 'empty input', {'empty input'}, statement, labels[0]
    return None


def claim(statement, questions, public, axes, meanings, options, cells, source):
    short = SHORT.fullmatch(statement)
    if short:
        if len(questions) != 1 or questions[0].count('?') != 1 or not questions[0].rstrip().endswith('?'):
            return None
        text = questions[0].strip()
        if not re.search(r'나요\?|인가요\?|니까\?|할까요\?|인지요\?|\b(?:should|does|is|do|may|can|will|would)\b', text, re.I):
            return None
    else:
        text = statement
    if ALTERNATIVE.search(text) or ILLUSTRATION.search(text) or re.search(r'[.!?]\s+\S|[;；]', text):
        return None
    if not axes:
        return collection_claim(text, source, options, cells) if not short else None
    condition, effect = split_condition(text)
    if not condition or QUALIFIED.search(condition) or re.search(r'(?<![a-z])(?:if|when|unless)\b|(?:하면|이면|으면|다면|경우에만|일 때)', effect, re.I):
        return None
    value = boolean_result(effect, meanings)
    if value not in options:
        return None
    if short and short[1].casefold() in ('아니요', '아니오', 'no'):
        value = 'False' if value == 'True' else 'True'
    bound = numeric_condition(condition, public, axes)
    return (*bound, value) if bound else None


def stated_outcome(statement, meanings):
    """Read just a conditional reply's consequence. The writer still has to witness its scope."""
    if SHORT.fullmatch(statement) or ALTERNATIVE.search(statement) or ILLUSTRATION.search(statement):
        return None
    condition, effect = split_condition(statement)
    if not condition or re.search(r'경우에만|일 때만|(?:하면|이면|으면|다면)\s|\b(?:except|unless|if|when)\b', effect, re.I):
        return None
    direct = boolean_result(effect, meanings)
    if direct:
        return direct
    permits = {meanings[k] for k in ('허용', '승인', '허가', 'allow', 'allowed', 'permitted', 'approved') if k in meanings}
    denies = {meanings[k] for k in ('거부', '거절', '불허', 'deny', 'denied', 'rejected') if k in meanings}
    if len(permits) == len(denies) == 1 and permits != denies:
        # Ability establishes a permission result only on an interface that defines both permission values.
        if re.search(r'할 수 있(?:습니다|다)[.! ]*$', effect):
            return next(iter(permits))
        if re.search(r'할 수 없(?:습니다|다)[.! ]*$', effect):
            return next(iter(denies))
    return None


def preserve_witnessed_choices(changed, proposed, prior, sources, outcomes, reply_ids, cells):
    old_texts = set(prior.get('received', []))
    new_ids = [sid for sid in outcomes if sources[sid] not in old_texts]
    changes = []
    for cell in cells:
        old = prior.get('witnesses', {}).get(cell)
        row = changed['regions'][cell]
        if cell in proposed or not old or old['result'] == row['result']:
            continue
        cited = [sid for sid in row['sources'] if sid in outcomes]
        common = [sid for sid in cited if sources[sid] in old['evidence']]
        value = old['result']
        if (not common or set(new_ids).intersection(cited)
                or {outcomes[s] for s in cited if outcomes[s]} != {value}
                or any(outcomes[s] != value for s in new_ids)):
            continue
        changed['regions'][cell] = dict(result=value, sources=row['sources'])
        changes.append(dict(region=cell, before=row['result'], after=value, replies=[reply_ids[sources[s]] for s in common],
                            reason='previously_implemented_same_answer'))
    return changes


def bind(original, packet, receipts, unique_scope=True, prior=None):
    """Overlay only regions whose condition and outcome are both witnessed. Preserve every other choice."""
    cells = list(packet['입력영역'])
    if set(cells) != set(original['regions']):
        raise ValueError('작성기가 받은 입력 영역과 반환한 영역이 다릅니다.')
    axes = numeric_axes(cells)
    sources, options = packet['원문'], packet['가능한결과']
    public = '\n'.join(v for k, v in sources.items() if k.startswith('P'))
    meanings = boolean_meanings(public)
    source_ids = {v: k for k, v in sources.items() if k.startswith('H')}
    windows, answers = dialogue(receipts)
    rules, unbound, proposed = [], [], {}
    for window in windows:
        for rid in window['answers']:
            statement = answers[rid]
            source = source_ids[statement]
            decision = claim(statement, window['questions'], public, axes, meanings, options, cells, source) if unique_scope else None
            if not decision:
                unbound.append(rid)
                continue
            label, covered, anchor, value = decision
            rule = dict(reply=rid, source=source, answer=statement, condition=label, anchor=anchor, result=value)
            rules.append(rule)
            for cell in covered:
                proposed.setdefault(cell, []).append(rule)

    changed = deepcopy(original)
    outcomes = {sid: stated_outcome(statement, meanings) for statement, sid in source_ids.items()} if axes and unique_scope else {}
    reply_ids = {text: rid for rid, text in reversed(list(answers.items()))}
    changes = preserve_witnessed_choices(changed, proposed, prior or {}, sources, outcomes, reply_ids, cells)
    issues = []
    for cell, claims in proposed.items():
        old = original['regions'][cell]
        values = {c['result'] for c in claims}
        value = next(iter(values)) if len(values) == 1 else 'defer'
        if len(values) > 1:
            issues.append(cell + ' · 담당자 회신이 겹치는 범위에서 충돌함')
        refs = list(dict.fromkeys([*(c['source'] for c in claims), *options[value]['근거'], *old['sources']]))[:5]
        if value != old['result'] or (value != 'defer' and (not old['sources'] or
                (options[value]['근거'] and not set(options[value]['근거']).intersection(old['sources'])))):
            changed['regions'][cell] = dict(result=value, sources=refs)
            changes.append(dict(region=cell, before=old['result'], after=value, replies=[c['reply'] for c in claims]))
    changes.sort(key=lambda c: cells.index(c['region']))
    issues.sort()
    witnesses = {}
    for cell, row in changed['regions'].items():
        evidence = [sources[sid] for sid in row['sources'] if sid in outcomes and outcomes[sid] == row['result']]
        if evidence:
            witnesses[cell] = dict(result=row['result'], evidence=evidence)
    return changed, dict(rules=rules, changes=changes, unbound=unbound, issues=issues,
                         witnesses=witnesses, received=list(source_ids))
