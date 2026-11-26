"""Assemble human-authorized, local edits for an existing allocation implementation."""
import ast
import re
import textwrap


def empty_scaffold(source):
    """Only a single empty public entry point can still need its first implementation."""
    try:
        nodes = ast.parse(source).body
    except (SyntaxError, ValueError):
        return False
    if len(nodes) != 1 or not isinstance(nodes[0], ast.FunctionDef):
        return False
    fn = nodes[0]
    if fn.name != 'simulate' or fn.decorator_list or len(fn.body) != 1:
        return False
    return ast.dump(fn) in _EMPTY_ENTRIES


_EMPTY_ENTRIES = {
    ast.dump(ast.parse('def simulate(initial_state, events):\n    ' + statement).body[0])
    for statement in ('pass', 'return {}', 'raise NotImplementedError', 'raise NotImplementedError()')
}


def review_packet(state):
    requests = {item['id']: item for item in state.get('requests', [])}
    packet = []
    for decision in state.get('decisions', []):
        if decision.get('source', 'human') != 'human':
            continue
        request_id = decision['request_id']
        request = requests.get(request_id, {})
        answer = decision.get('answer') or {}
        reviews = []
        for record in state.get('review_log', []):
            if request_id not in record.get('request_ids', []) and request_id not in record.get('affected_decision_ids', []):
                continue
            reviews.append({k: record[k] for k in ('id', 'monitor_id', 'version', 'decision', 'reason') if k in record})
        packet.append({'request_id': request_id, 'key': decision.get('key', request.get('key')),
                       'question': request.get('question', ''), 'status': request.get('status', ''),
                       'answer': {'text': answer.get('text', '')}, 'note': decision.get('note', ''),
                       'reviews': reviews})
    return packet


def model_view(envelope):
    """Keep one verbatim copy of every owner reply in the scheduler's wire request."""
    state = envelope.get('project_state') or {}
    if 'scheduling_decisions' not in state:
        return envelope
    state = dict(state)
    if 'monitor_feedback' in state:
        state['monitor_feedback']=[{k:v for k,v in m.items() if k!='last_call_id'} for m in state['monitor_feedback']]
    if envelope.get('role') == 'monitor':
        state.pop('event_completions',None)
    if envelope.get('action') == 'inspect_schedule_patch':
        state['code'] = '\n'.join(f'L{i}  {line}' for i,line in enumerate(state['code'].splitlines(),1))
        return dict(envelope,project_state=state)
    if 'decisions' not in state:
        return envelope
    state['decisions'] = [{k: d[k] for k in ('request_id','key','source') if k in d} for d in state['decisions']]
    state['requests'] = [{k:v for k,v in r.items() if k != 'answer'} for r in state.get('requests', [])]
    if envelope.get('action') == 'implement' and state.get('schedule_patch_required'):
        carried = carried_decisions(state)
        state['required_decision_ids'] = [k for k in state['required_decision_ids'] if k not in carried]
        state['preserved_decisions'] = [{'request_id':r['request_id'],'key':r['key']} for r in state['scheduling_decisions']
                                        if r['request_id'] in carried]
        state['scheduling_decisions'] = [r for r in state['scheduling_decisions'] if r['request_id'] not in carried]
        state['decisions'] = [r for r in state['decisions'] if r['request_id'] not in carried]
        state['requests'] = [r for r in state['requests'] if r['id'] not in carried]
        state['owner_passages'] = {d['request_id']:owner_passages(d) for d in state['scheduling_decisions']}
    return dict(envelope, project_state=state)


def carried_decisions(state):
    """Only decisions accepted on a previous version can carry their disposition over."""
    active = set(state.get('editable_decision_ids', []))
    carried={r['id']:r['status'] for r in state['requests']
            if r['id'] not in active and r['status'] in ('applied','acknowledged')
            and r.get('applied_version' if r['status']=='applied' else 'acknowledged_version') is not None}
    carried.update({k:v for k,v in state.get('accepted_in_draft',{}).items() if k not in active})
    return carried


def owner_passages(decision):
    lines = []
    for text in (decision['answer']['text'], decision.get('note','')):
        lines.extend(line.strip() for line in text.splitlines() if line.strip())
    return {f'H{i}':line for i,line in enumerate(lines,1)}


def _tree(source):
    try:
        tree = ast.parse(source)
        compile(tree, '<allocation>', 'exec')
    except (SyntaxError, ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError('수정 전후의 파이썬 코드가 유효해야 합니다.') from exc
    return tree


def _pending_nodes(tree, source):
    """Explicitly unfinished statements are the only sites that may expand to a suite."""
    locations = _Locations(source)
    for parent in ast.walk(tree):
        for field, body in ast.iter_fields(parent):
            if not isinstance(body, list):
                continue
            for index, node in enumerate(body):
                if isinstance(node, ast.Raise):
                    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
                    if not isinstance(exc, ast.Name) or exc.id != 'NotImplementedError':
                        continue
                elif not (isinstance(node, ast.Pass) and len(body) == 1 and not isinstance(parent, ast.ClassDef)):
                    continue
                start, end = locations.span(node)
                yield f'@pending:{node.lineno}:{node.col_offset}', parent, field, index, start, end


def pending_sites(source):
    if not source:
        return {}
    try:
        return {key: source[a:b] for key, _, _, _, a, b in _pending_nodes(_tree(source), source)}
    except ValueError:
        return {}


def _fill_pending(source, start, end, replacement):
    tree = _tree(source)
    site = next((s for s in _pending_nodes(tree, source) if s[-2:] == (start,end)), None)
    if site is None:
        raise ValueError('보류된 위치가 현재 소스와 다릅니다.')
    _, parent, field, index, _, _ = site
    prefix = source[source.rfind('\n',0,start)+1:start]
    if prefix.strip():
        raise ValueError('독립된 줄에 있는 보류 지점만 여러 문장으로 구현할 수 있습니다.')
    # The first line starts at the old statement. Internal indentation stays relative to it.
    block = textwrap.dedent(replacement.strip('\n')).rstrip()
    nodes = ast.parse(block).body
    if not nodes or any(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Import,ast.ImportFrom,
                                       ast.Global,ast.Nonlocal)) for n in ast.walk(ast.Module(body=nodes,type_ignores=[]))):
        raise ValueError('보류된 분기에 해당하는 실행문만 제출하세요.')
    body = getattr(parent,field)
    body[index:index+1] = nodes
    candidate = source[:start] + ('\n'+prefix).join(block.splitlines()) + source[end:]
    if ast.dump(_tree(candidate)) != ast.dump(tree):
        raise ValueError('보류 지점 밖의 코드 구조가 변경됐습니다.')
    if any(s[-2] >= start and s[-2] < start+len(candidate)-len(source)+end-start
           for s in _pending_nodes(_tree(candidate), candidate)):
        raise ValueError('수정한 분기에 미구현 지점이 남았습니다.')
    return candidate


class _Locations:
    def __init__(self, source):
        self.source = source
        self.lines = source.splitlines(keepends=True)
        offset = 0
        self.starts = []
        for line in self.lines:
            self.starts.append(offset)
            offset += len(line)

    def position(self, line, column):
        # Python AST columns count UTF-8 bytes, including non-ASCII string literals.
        return self.starts[line - 1] + len(self.lines[line - 1].encode('utf-8')[:column].decode('utf-8'))

    def span(self, node):
        return (self.position(node.lineno, node.col_offset),
                self.position(node.end_lineno, node.end_col_offset))


_SIMPLE = (ast.Return, ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Assert)
_GUARDS = {ast.If: 'test', ast.While: 'test', ast.For: 'iter'}


def _sites(tree, source, start, end, *, wrappers=False):
    """Find a single statement or control predicate enclosing the exact replacement."""
    locations = _Locations(source)
    sites = {}

    def visit(node, path, parent=None, field=None, index=None):
        if wrappers and isinstance(node, ast.If) and locations.span(node) == (start, end):
            sites[path] = (parent, field, index, node)
        if isinstance(node, _SIMPLE):
            # Standalone string literals and docstrings cannot authorize an executable edit.
            inert = isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
            left, right = locations.span(node)
            if not inert and left <= start < end <= right:
                sites[path] = (parent, field, index, node)
        predicate = _GUARDS.get(type(node))
        if predicate:
            expr = getattr(node, predicate)
            left, right = locations.span(expr)
            header_start, _ = locations.span(node)
            colon = right
            while colon < len(source) and source[colon] in ' \t':
                colon += 1
            if (left <= start < end <= right or (
                    colon < len(source) and source[colon] == ':' and
                    header_start <= start < end <= colon + 1)):
                sites[path + (predicate,)] = (node, predicate, None, expr)
        for key, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                visit(value, path + (key,), node, key)
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        visit(child, path + (key, i), node, key, i)
    visit(tree, ())
    return sites


def has_code_evidence(candidate, excerpt):
    """Require a unique, complete executable statement, computed expression or actual control predicate."""
    if not isinstance(candidate, str) or not isinstance(excerpt, str) or not excerpt.strip():
        return False
    mark = re.fullmatch(r'L([1-9]\d*)', excerpt.strip())
    if mark:
        try:
            tree = _tree(candidate)
        except ValueError:
            return False
        return any(isinstance(n, (*_SIMPLE, *_GUARDS)) and n.lineno == int(mark[1])
                   and not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)) for n in ast.walk(tree))
    found = candidate.find(excerpt)
    if found < 0 or candidate.find(excerpt, found + 1) >= 0:
        return False
    start = found + len(excerpt) - len(excerpt.lstrip())
    end = found + len(excerpt.rstrip())
    try:
        tree = _tree(candidate)
    except ValueError:
        return False
    positions = _Locations(candidate)
    calculated = (ast.Compare, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Subscript, ast.Call)
    for _, _, _, node in _sites(tree, candidate, start, end).values():
        if positions.span(node) == (start, end) and not isinstance(node, ast.Constant):
            return True
        for expr in ast.walk(node):
            if isinstance(expr, calculated) and positions.span(expr) == (start, end):
                return True
    for node in ast.walk(tree):
        guard = _GUARDS.get(type(node))
        if guard is not None and positions.span(node)[0] == start:
            guard_end = positions.span(getattr(node, guard))[1]
            if guard_end < end and candidate[guard_end:end].strip() == ':':
                return True
    return False


def review_path(source, excerpt):
    """Show the enclosing guards, neighbouring operations and local callees of a disputed line."""
    tree=_tree(source)
    lines=source.splitlines()
    match = re.fullmatch(r'L([1-9]\d*)',excerpt or '')
    if match:
        line=int(match[1])
    elif excerpt and source.count(excerpt)==1:
        line=source.count('\n',0,source.index(excerpt))+1
    else:
        return {}
    enclosing=[n for n in ast.walk(tree) if isinstance(n,ast.stmt) and n.lineno<=line<=n.end_lineno]
    if not enclosing:
        return {}
    node=min(enclosing,key=lambda s:s.end_lineno-s.lineno)
    parents={id(x):(n,k,i) for n in ast.walk(tree) for k,val in ast.iter_fields(n) if isinstance(val,list)
             for i,x in enumerate(val) if isinstance(x,ast.stmt)}
    guards,adjacent,calls=[],{},set()
    def include(stmt):
        adjacent[stmt.lineno]=lines[stmt.lineno-1].strip()
        calls.update(n.func.id for n in ast.walk(stmt) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name))
    include(node)
    while id(node) in parents:
        parent,field,i=parents[id(node)]
        if isinstance(parent,ast.Module):
            break
        block=getattr(parent,field)
        for neighbour in block[max(i-2,0):i]+block[i+1:i+3]:
            include(neighbour)
        if isinstance(parent,ast.If):
            guards.append({'line':parent.lineno,'condition':ast.get_source_segment(source,parent.test),'arm':field})
        if isinstance(parent,ast.FunctionDef):
            break
        node=parent
    helpers={}
    for fn in tree.body:
        if isinstance(fn,ast.FunctionDef) and fn.name in calls and fn.name!='simulate':
            helpers[fn.name]='\n'.join(f'L{j}  {lines[j-1]}' for j in range(fn.lineno,min(fn.end_lineno,fn.lineno+55)+1))
    return {'enclosing_conditions':guards,'adjacent_source':[f'L{k}  {v}' for k,v in sorted(adjacent.items())],
            'called_functions':helpers}


def _wraps_original(old, new):
    """The original statement must survive verbatim in meaning as the sole fallback."""
    if not isinstance(old, _SIMPLE) or not isinstance(new, ast.If) or len(new.body) != 1 or len(new.orelse) != 1:
        return False
    action = new.body[0]
    if not isinstance(action, _SIMPLE) or (isinstance(action, ast.Expr) and isinstance(action.value, ast.Constant)):
        return False
    if ast.dump(new.orelse[0]) != ast.dump(old) or ast.dump(action) == ast.dump(old):
        return False
    # A constant gate would replace all previous behavior unconditionally.
    for part in ast.walk(new.test):
        if isinstance(part, (ast.NamedExpr, ast.Lambda, ast.Yield, ast.YieldFrom, ast.Await)):
            return False
        if isinstance(part, ast.BoolOp) and any(isinstance(value, ast.Constant) for value in part.values):
            return False
        if isinstance(part, ast.Compare) and any(ast.dump(a) == ast.dump(b) for a, b in
                zip([part.left, *part.comparators], part.comparators)):
            return False
    return any(isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) for n in ast.walk(new.test))


def _masked(tree, site):
    parent, field, index, original = site
    placeholder = ast.Pass() if isinstance(original, ast.stmt) else ast.Constant(None)
    if index is None:
        setattr(parent, field, placeholder)
    else:
        getattr(parent, field)[index] = placeholder
    try:
        return ast.dump(tree)
    finally:
        if index is None:
            setattr(parent, field, original)
        else:
            getattr(parent, field)[index] = original


def _split_assignment(source, start, before, after):
    """Insert a relative block of assignments at exactly one standalone assignment."""
    if '\n' not in after.strip():
        return None
    start += len(before) - len(before.lstrip(' \t'))
    before = before.strip(' \t')
    indent = source[source.rfind('\n', 0, start) + 1:start]
    if indent.strip():
        return None
    tree = _tree(source)
    locations = _Locations(source)
    for parent in ast.walk(tree):
        for _, body in ast.iter_fields(parent):
            if not isinstance(body, list):
                continue
            for index, stmt in enumerate(body):
                if not isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    continue
                if locations.span(stmt) != (start, start + len(before)):
                    continue
                relative = textwrap.dedent(after.strip('\n')).rstrip()
                # Accept either a relative snippet or continuation lines already at site indent.
                for block in dict.fromkeys((relative, textwrap.dedent(indent + relative))):
                    try:
                        assignments = ast.parse(block).body
                    except (ValueError, SyntaxError):
                        continue
                    if len(assignments) < 2 or not all(isinstance(n, (ast.Assign, ast.AnnAssign))
                                                       for n in assignments):
                        continue
                    candidate = source[:start] + ('\n' + indent).join(block.split('\n')) + source[start+len(before):]
                    # Check exact structure outside the selected site and literal values inside it.
                    body[index:index+1] = assignments
                    if ast.dump(_tree(candidate)) == ast.dump(tree):
                        return candidate
                    body[index:index+len(assignments)] = [stmt]
                return None
    return None


def _one_edit(source, start, before, after):
    expanded = _split_assignment(source, start, before, after)
    if expanded is not None:
        return expanded
    candidate = source[:start] + after + source[start + len(before):]
    old, new = _tree(source), _tree(candidate)
    if ast.dump(old) == ast.dump(new):
        raise ValueError('계산이나 판단을 실제로 변경하는 수정이어야 합니다.')
    def anchors(tree, text, fragment, *, wrappers=False):
        left = start + len(fragment) - len(fragment.lstrip())
        right = start + len(fragment.rstrip())
        return _sites(tree, text, left, right, wrappers=wrappers)
    old_sites = anchors(old, source, before)
    new_sites = anchors(new, candidate, after, wrappers=True)
    for key in old_sites.keys() & new_sites.keys():
        left, right = old_sites[key], new_sites[key]
        # A replacement in a control header can change only the guard, never its body.
        if isinstance(left[3], ast.stmt) and type(left[3]) is not type(right[3]):
            if not _wraps_original(left[3], right[3]):
                continue
        if _masked(old, left) == _masked(new, right):
            return candidate
    raise ValueError('변경 범위는 하나의 기존 계산문이나 조건식 안에 있어야 합니다.')


def apply_edits(previous, edits, decisions, active_ids):
    """Return source with the approved nonoverlapping spans replaced, atomically."""
    if not isinstance(previous, str) or not isinstance(edits, list):
        raise ValueError('이전 소스와 수정 목록이 필요합니다.')
    allowed = set(active_ids)
    human = {d['request_id']: d for d in decisions if d.get('source', 'human') == 'human'}
    replacements = []
    pending = {key:(a,b) for key,_,_,_,a,b in _pending_nodes(_tree(previous),previous)} if edits else {}
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != {'request_id', 'quote', 'before', 'after'}:
            raise ValueError('수정에는 질문 ID, 담당자 원문 인용과 수정 전후 코드가 필요합니다.')
        request_id, quote, before, after = (edit[key] for key in ('request_id', 'quote', 'before', 'after'))
        if not all(isinstance(s, str) and s.strip() for s in (request_id, quote, before, after)):
            raise ValueError('빈 인용이나 빈 코드로 수정할 수 없습니다.')
        decision = human.get(request_id)
        if request_id not in allowed or decision is None:
            raise ValueError('이번에 반영할 담당자 답변 ID가 아닙니다.')
        answer = decision.get('answer') or {}
        quote = owner_passages(decision).get(quote, quote)
        if not any(isinstance(text, str) and quote in text for text in (answer.get('text'), decision.get('note'))):
            raise ValueError('인용은 해당 담당자 답변 또는 조언의 원문이어야 합니다.')
        if before in pending:
            start, end = pending[before]
        else:
            start = previous.find(before)
            if start < 0 or previous.find(before, start + 1) >= 0:
                raise ValueError('수정 전 코드는 이전 파일에서 정확히 한 번 찾아야 합니다.')
            end = start + len(before)
        is_pending = (start,end) in pending.values()
        if is_pending:
            if len(after) > 8000:
                raise ValueError('보류 지점에 넣을 코드가 너무 큽니다.')
        elif any(len(s) > 1200 or len(s.splitlines()) > 8 for s in (before, after)) or before.strip() == previous.strip():
            raise ValueError('파일이나 넓은 코드 범위를 통째로 바꿀 수 없습니다.')
        replacements.append((start, end, after, is_pending))
    replacements.sort(key=lambda row: row[0])
    for (_, end, _, _), (next_start, _, _, _) in zip(replacements, replacements[1:]):
        if end > next_start:
            raise ValueError('서로 겹치는 코드 수정입니다.')
    result = previous
    for start, end, after, is_pending in reversed(replacements):
        try:
            if is_pending:
                result = _fill_pending(result, start, end, after)
            else:
                result = _one_edit(result, start, result[start:end], after)
        except (SyntaxError, RecursionError) as exc:
            raise ValueError('해당 편집의 파이썬 구문이나 들여쓰기를 확인하세요.') from exc
    return result

