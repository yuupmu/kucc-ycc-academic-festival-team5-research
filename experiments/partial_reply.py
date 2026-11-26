"""A local editor for integer decision trees with explicitly unfinished Boolean branches."""
import ast
import re
from collections import defaultdict

from backend.allocation_repair import pending_sites
from backend.structured_output import array, obj
from experiments.guarded_reply import check_predicate, scalar_parameter, term


UNKNOWN = '미정'
ABSENT = '직접 근거 없음'


def choices(items):
    return {'type': 'string', 'enum': list(items)}


SCOPE = """코드 검토의 위치를 연결하세요. 각 지적이 가리키는 미구현 문장 번호를 모두 고르세요.
여러 지적이 같은 문장을 가리킬 수 있습니다. 지적을 해결하기 위해 이미 구현된 곳까지 수정해야 하면 '다른 위치'도 고르세요.
어디인지 정할 수 없으면 '미확인'을 고르세요. 지적이나 질문에서 담당자의 정책을 정하지 마세요."""

DECIDE = """정수 입력에 대한 요구사항 분석입니다. 주어진 입력 영역 전체에 적용할 동작을 명세와 담당자의 실제 회신에서 읽으세요.
먼저 이 영역에서 해당 동작을 지시하는 문장의 번호를 선택하고 그 문장에 따라 반환값을 선택하세요. 다른 문장은 이름과 수치의 대응, 반환값의 의미를 해석하는 데 쓸 수 있습니다.
값이나 용어를 정의하는 문장, 담당자에게 문의할 수 있다는 문장, 반환 형식의 설명만으로는 어느 행동을 선택할지 알 수 없습니다.
부등식이 등호까지 포함되는지는 문장 그대로 읽으세요. 상반된 두 행동이 모두 가능한 경우 직접 근거 없음과 미정을 선택하세요.
명세에 이미 명시된 일반 규칙은 회신에 반복되어 있지 않아도 적용합니다. 질문은 회신의 문맥이며 그 자체는 근거가 아닙니다."""

VERIFY = """독립적으로 근거의 적용 범위를 점검하세요. 조건에 해당하는 모든 입력에 대해 인용 문장이 제시된 반환값을 실제로 지시하나요?
다른 문장은 수치의 이름이나 반환값의 뜻을 설명할 수 있습니다. 관행이나 추측, 아직 답하지 않은 질문은 근거로 쓰지 않습니다.
인용문을 지키면서도 해당 영역에서 다른 반환값을 선택할 수 있다면 '근거 부족', 그렇지 않으면 '근거 충분'을 고르세요."""

ASK = """회신을 반영하고도 결정할 수 없는 입력 영역이 남았습니다. 담당자가 그 영역의 행동을 정해 줄 수 있도록 한국어 일상어로 질문 한 문장만 작성하세요.
미결 영역만 구체적으로 물으세요. 이미 확인된 내용을 다시 묻거나 답을 대신 정하지 마세요."""


def scope(brief, source, questions, issues, ask):
    sites = pending_sites(source)
    aliases = {f'S{i}': k for i, k in enumerate(sites, 1)}
    findings = {f'R{i}': issue for i, issue in enumerate(issues, 1)}
    if not findings:
        return {'accepted': bool(sites), 'sites': list(sites), 'findings': {}, 'calls': []}
    options = [*aliases, '다른 위치', '미확인']
    packet = dict(명세=brief, 초안=source, 질문=questions, 지적=findings,
                  미구현={a: {'위치': k, '문장': sites[k]} for a, k in aliases.items()})
    schema = obj({key: array(choices(options), 1, len(options)) for key in findings})
    key, result = ask('scope', SCOPE, packet, schema, 220)
    labels = {item for group in (result or {}).values() for item in group}
    return dict(accepted=bool(labels) and labels <= aliases.keys(),
                sites=[v for k, v in aliases.items() if k in labels],
                findings=result, aliases=aliases, calls=[key])


def passages(brief, answers):
    parts = {}
    for prefix, passage in [('P', brief), *((f'H{i}.', a) for i, a in enumerate(answers, 1))]:
        for i, line in enumerate(re.split(r'(?<=[.!?。])\s+|\n+', passage.strip()), 1):
            if line:
                parts[f'{prefix}{i}'] = line
    return parts


def cells(source, name, evidence):
    # These are cuts in the supplied requirements and current code, never evaluation cases.
    cut = {int(v) for line in evidence.values() for v in re.findall(r'(?<![\d.])[-+]?\d+(?![\d.])', line)}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            for value in (node.left, *node.comparators):
                if not isinstance(value, ast.Name):
                    cut.add(term(value, name, 0))
    points = sorted(cut)
    if not points:
        return [('True', 0)]
    regions = [(f'{name} < {points[0]}', points[0]-1)]
    for i, point in enumerate(points):
        if i and points[i-1]+1 < point:
            regions.append((f'{points[i-1]} < {name} < {point}', points[i-1]+1))
        regions.append((f'{name} == {point}', point))
    return [*regions, (f'{name} > {points[-1]}', points[-1]+1)]


def destination(body, name, witness):
    for node in body:
        if isinstance(node, ast.If):
            branch = node.body if check_predicate(node.test, name, witness) else node.orelse
            target = destination(branch, name, witness)
            if target is not None:
                return target
        elif isinstance(node, ast.Return):
            return ('return', node.value.value)
        elif isinstance(node, ast.Raise):
            return ('raise', f'@pending:{node.lineno}:{node.col_offset}')
    return None


def decision(expr, evidence, questions, ask):
    packet = dict(입력영역=expr, 명세와회신=evidence, 회신별질문=questions)
    schema = obj(dict(근거=choices([*evidence, ABSENT]), 반환=choices(['True', 'False', UNKNOWN])))
    key, answer = ask('interpret', DECIDE, packet, schema, 96)
    record = dict(region=expr, interpretation=answer, calls=[key], value=UNKNOWN)
    if not answer or answer['근거'] == ABSENT or answer['반환'] == UNKNOWN:
        return record
    citation = evidence[answer['근거']]
    key, checked = ask('entailment', VERIFY, dict(**packet, 인용문=citation, 제안=answer['반환']),
                       obj(dict(판정=choices(['근거 충분', '근거 부족']))), 70)
    record.update(verification=checked, quote=citation)
    record['calls'].append(key)
    if checked and checked['판정'] == '근거 충분':
        record['value'] = answer['반환']
    return record


def fill(source, assignments):
    # Every edit starts at a genuine, stand-alone pending raise. Keep the original raise as the
    # fallback when some reachable region is still unknown. Existing returns are never rewritten.
    sites, lines = pending_sites(source), source.splitlines(keepends=True)
    for site, rows in sorted(assignments.items(), key=lambda pair: int(pair[0].split(':')[1]), reverse=True):
        index = int(site.split(':')[1])-1
        line = lines[index]
        content = line.rstrip('\r\n')
        if site not in sites or content.strip() != sites[site] or not sites[site].startswith('raise '):
            raise ValueError('Unsupported pending statement')
        prefix = content[:len(content)-len(content.lstrip())]
        end = line[len(content):]
        sep = end or ('\r\n' if '\r\n' in source else '\n')
        known = [r for r in rows if r['value'] != UNKNOWN]
        if not known:
            continue
        if any(r['value'] not in ('True', 'False') for r in known):
            raise ValueError('Unsupported return')
        complete = len(known) == len(rows)
        default = known[-1]['value'] if complete else None
        statements = []
        for row in known:
            if row['value'] != default:
                statements += [prefix+'if '+row['region']+':', prefix+'    return '+row['value']]
        statements.append(prefix+'return '+default if complete else content)
        lines[index] = sep.join(statements)+end
    candidate = ''.join(lines)
    ast.parse(candidate)
    return candidate


def revise(brief, source, answers, questions, locations, ask):
    evidence = passages(brief, answers)
    all_sites = pending_sites(source)
    # The scope router already checked the original findings. The old structural checker also
    # expects exactly one evidence packet, so present the final natural-language receipt there.
    name = scalar_parameter(dict(code=source, brief=brief, pending=all_sites, review=[],
                                 evidence={'receipt': answers[-1]})) if answers else None
    info = dict(decisions=[], unresolved=[], calls=[], route='unavailable')
    if not name or not locations or not set(locations) <= all_sites.keys():
        return source, info
    body = ast.parse(source).body[0].body
    assignments = defaultdict(list)
    for expr, witness in cells(source, name, evidence):
        dest = destination(body, name, witness)
        if dest is None or (dest[0] == 'raise' and dest[1] not in all_sites):
            return source, info
        if dest[0] != 'raise' or dest[1] not in locations:
            continue
        row = decision(expr, evidence, questions, ask)
        row['site'] = dest[1]
        assignments[dest[1]].append(row)
        info['decisions'].append(row)
        info['calls'].extend(row['calls'])
        if row['value'] == UNKNOWN:
            info['unresolved'].append(expr)
    info['route'] = 'request clarification' if info['unresolved'] else 'implement'
    return fill(source, assignments), info


def remaining_locations(source, brief, answers, unresolved):
    if not unresolved:
        return []
    tree = ast.parse(source).body[0]
    name = (tree.args.posonlyargs + tree.args.args)[0].arg
    regions = dict(cells(source, name, passages(brief, answers)))
    sites = []
    for expr in unresolved:
        kind, location = destination(tree.body, name, regions[expr])
        if kind != 'raise' or location not in pending_sites(source):
            raise ValueError('An unresolved input has no surviving pending statement')
        sites.append(location)
    return list(dict.fromkeys(sites))


def clarification(brief, answers, unresolved, ask):
    if not unresolved:
        return None, []
    key, result = ask('clarify', ASK, dict(명세=brief, 담당자회신=answers, 미결영역=unresolved),
                      obj(dict(질문={'type': 'string', 'maxLength': 260})), 200)
    return result['질문'].strip() if result else None, [key]
