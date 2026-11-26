"""Offer local completions for a pending capacity event using the scheduler's own continuation."""
import ast
import json
import re
import textwrap


def _subscript(node, variable, key):
    return (isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name) and node.value.id==variable
            and isinstance(node.slice,ast.Constant) and node.slice.value==key)


def _field_variable(statements, field):
    for node in reversed(statements):
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            expr = node.value
            if (isinstance(expr,ast.Subscript) and isinstance(expr.value,ast.Name)
                    and _subscript(expr,expr.value.id,field)):
                return node.targets[0].id,expr.value.id
    return None,None


def _completion(source, loop, valid, branch, event, op_var, caps, code, decision, outcomes):
    available = {}
    after = valid.body[valid.body.index(branch)+1:]
    footer = loop.body[loop.body.index(valid)+1:]
    # An established common result path must persist the chosen code. Keep that exact path.
    if not footer or not any(isinstance(n,ast.Name) and n.id==code and isinstance(n.ctx,ast.Load)
                             for s in footer for n in ast.walk(s)):
        return available
    # Only offer unconditionally invoked existing helpers after the event-specific operations.
    joins = [i for i,s in enumerate(after) if isinstance(s,ast.Assign) and isinstance(s.value,ast.Call)
             and any(isinstance(a,ast.Name) and a.id==caps for a in s.value.args)]
    if len(joins)!=1:
        return available
    lines=source.splitlines()
    def copy_statements(stmts, specialize=False):
        chunks=[]
        for stmt in stmts:
            # The enclosing branch already established the event kind. A branch for
            # a different literal event cannot run here or provide any variables.
            if specialize and isinstance(stmt,ast.If) and not stmt.orelse:
                test=stmt.test
                if (isinstance(test,ast.Compare) and isinstance(test.left,ast.Name) and test.left.id==op_var
                        and len(test.ops)==1 and isinstance(test.ops[0],ast.Eq)
                        and isinstance(test.comparators[0],ast.Constant) and test.comparators[0].value!='set_capacity'):
                    continue
            chunks.append(textwrap.dedent('\n'.join(lines[stmt.lineno-1:stmt.end_lineno])))
            if any(isinstance(n,ast.Name) and n.id==op_var and isinstance(n.ctx,ast.Store) for n in ast.walk(stmt)):
                specialize=False
        return '\n'.join(chunks)
    hole=branch.body[0]
    marker=f'@pending:{hole.lineno}:{hole.col_offset}'
    for join,description in ((joins[0], '기존 배정 함수와 공통 결과 기록을 실행'),(len(after),'공통 결과 기록만 실행')):
        for outcome in outcomes:
            replacement = [f"{caps}[{event}['resource']] = {event}['capacity']", f'{code} = {outcome!r}',
                           copy_statements(after[join:],True),copy_statements(footer),'continue']
            key=f'@event:{hole.lineno}:{join}:{outcome}'
            available[key] = dict(request_id=decision['request_id'],before=marker,after='\n'.join(s for s in replacement if s),
                result=outcome,
                description=f'set_capacity에서 요청한 자원 총량을 설정하고 {outcome}를 기록. {description}.')
    return available


def capacity_options(state):
    source = state.get('code')
    if not source or not state.get('pending_code_sites'):
        return {}
    public_codes = re.search(r'(?m)^- code 값:\s*([^\n]+)',state.get('task',''))
    if not public_codes:
        return {}
    vocabulary = set(re.findall(r'[a-z][a-z_]*',public_codes[1]))
    active = set(state['editable_decision_ids'])
    decisions = [d for d in state['scheduling_decisions'] if d['request_id'] in active and
                 'set_capacity' in (d['question']+' '+d['answer']['text']+' '+d.get('note',''))]
    if len(decisions)!=1:
        return {}
    decision = decisions[0]
    answer = decision['answer']['text']+' '+decision.get('note','')
    outcomes = list(dict.fromkeys(w for w in re.findall(r'\b[a-z][a-z_]*\b',answer,re.ASCII) if w in vocabulary))
    if not outcomes:
        return {}
    tree = ast.parse(source)
    fn = next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='simulate'),None)
    if fn is None or len(fn.args.args)!=2:
        return {}
    initial = fn.args.args[0].arg
    maps = [s.targets[0].id for s in fn.body if isinstance(s,ast.Assign) and len(s.targets)==1 and
            isinstance(s.targets[0],ast.Name) and any(_subscript(n,initial,'capacities') for n in ast.walk(s.value))]
    if len(maps)!=1:
        return {}
    options = {}
    for loop in (s for s in fn.body if isinstance(s,ast.For) and not s.orelse):
        for valid in (s for s in loop.body if isinstance(s,ast.If) and not s.orelse):
            test = valid.test
            if not (isinstance(test,ast.Compare) and isinstance(test.left,ast.Name) and len(test.ops)==1
                    and isinstance(test.ops[0],ast.Is) and isinstance(test.comparators[0],ast.Constant)
                    and test.comparators[0].value is None):
                continue
            for i,branch in enumerate(valid.body):
                if not isinstance(branch,ast.If) or branch.orelse or len(branch.body)!=1:
                    continue
                marker=f'@pending:{branch.body[0].lineno}:{branch.body[0].col_offset}'
                if marker not in state['pending_code_sites']:
                    continue
                op,event = _field_variable(valid.body[:i],'op')
                expr = branch.test
                if (op and isinstance(expr,ast.Compare) and isinstance(expr.left,ast.Name) and expr.left.id==op
                        and len(expr.ops)==1 and isinstance(expr.ops[0],ast.Eq)
                        and isinstance(expr.comparators[0],ast.Constant) and expr.comparators[0].value=='set_capacity'):
                    options.update(_completion(source,loop,valid,branch,event,op,maps[0],test.left.id,
                                               decision,outcomes))
    return options


def capacity_check(outcome):
    """Exercise the accepted update on an empty queue using the public output contract."""
    capacities = dict(seats=1,laptops=1,projectors=0)
    updated = dict(capacities, seats=2)
    event = dict(event_id='e1',op='set_capacity',resource='seats',capacity=2)
    query = dict(initial_state={'capacities':capacities},events=[event])
    expected = dict(event_results=[dict(event_id='e1',code=outcome,replayed=False,admitted=[])],
                    final_state=dict(capacities=updated,available=updated,reservations=[],waitlist=[]),notifications=[])
    return dict(input_json=json.dumps(query),expected_json=json.dumps(expected))
