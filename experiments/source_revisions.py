"""Compile source-linked amendments before an existing decision function's original statements."""
import ast
import copy
import re

from experiments import rule_edits as rules


UNIT_SECONDS = {'seconds':1, 'minutes':60, 'hours':3600, 'days':86400}
KOREAN_UNITS = {'초':'seconds', '분':'minutes', '시간':'hours', '일':'days'}


def public_quantities(clauses):
    found = {}
    for key, sentence in clauses.items():
        for match in re.finditer(r'(?<![\d.])(\d+)\s*(시간|분|초|일)', sentence):
            amount = int(match[1])
            unit = KOREAN_UNITS[match[2]]
            found[f'T{len(found)+1}'] = dict(source=key, text=match[0], amount=amount, unit=unit,
                                               seconds=amount*UNIT_SECONDS[unit])
    return found


def entry(tree):
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'allow_cancel']
    if len(funcs) != 1:
        return None
    fn = funcs[0]
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if names[:2] != list(rules.INPUTS) or len(names)-len(fn.args.defaults) > 2:
        return None
    return None if any(v is None for v in fn.args.kw_defaults) else fn


def returns_in(function):
    """Index only returns belonging to this function, never nested definitions or class bodies."""
    nodes = []
    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(node, ast.Return):
            nodes.append(node)
        for child in ast.iter_child_nodes(node):
            visit(child)
    for statement in function.body:
        visit(statement)
    ordered = sorted(nodes, key=lambda n: (n.lineno, n.col_offset))
    return {f'E{i}':n for i,n in enumerate(ordered,1)}


def overlap(box, other):
    return all(max(lo,other[k][0]) <= min(hi,other[k][1]) for k,(lo,hi) in box.items())


def site_bounds(function):
    """Necessary conditions for simple if/return paths. An unknown expression adds no restriction."""
    if any((isinstance(n,ast.stmt) and n is not function and not isinstance(n,(ast.If,ast.Return,ast.Pass)))
           or isinstance(n,ast.NamedExpr) for n in ast.walk(function)):
        return {}
    ops = {ast.Lt:'<', ast.LtE:'<=', ast.Gt:'>', ast.GtE:'>=', ast.Eq:'=='}
    inverse = {'<':'>=', '<=':'>', '>':'<=', '>=':'<'}
    sites = {id(node):name for name,node in returns_in(function).items()}
    paths = {}

    def conditions(test, truth):
        if isinstance(test,ast.UnaryOp) and isinstance(test.op,ast.Not):
            return conditions(test.operand, not truth)
        if isinstance(test,ast.BoolOp) and isinstance(test.op, ast.And if truth else ast.Or):
            return [row for sub in test.values for row in conditions(sub,truth)]
        if not isinstance(test,ast.Compare) or len(test.ops) != 1 or not isinstance(test.left,ast.Name):
            return []
        op, right = ops.get(type(test.ops[0])), test.comparators[0]
        if not truth:
            op = inverse.get(op)
        if test.left.id not in rules.INPUTS or op is None or not isinstance(right,ast.Constant) or type(right.value) is not int:
            return []
        return [dict(input=test.left.id, op=op, seconds=right.value)]

    def block(statements, known):
        for stmt in statements:
            if isinstance(stmt,ast.Return):
                paths[sites[id(stmt)]] = rules.bounds(known)
                return True
            if isinstance(stmt,ast.If):
                yes, no = conditions(stmt.test,True), conditions(stmt.test,False)
                exits_yes, exits_no = block(stmt.body,known+yes), block(stmt.orelse,known+no)
                if exits_yes and exits_no:
                    return True
                if exits_yes:
                    known = known + no
                elif exits_no:
                    known = known + yes
        return False
    block(function.body, [])
    return paths


class SourceRevisions:
    def __init__(self, draft, clauses):
        self.draft = draft
        self.clauses = clauses
        self.quantities = public_quantities(clauses)
        try:
            self.tree = ast.parse(draft)
        except (SyntaxError, ValueError):
            self.tree = None
        self.has_base = self.tree is not None and entry(self.tree) is not None
        self.sites = {'ENTRY':'함수 진입 시점'}
        self.literal_returns = {}
        self.reachable_bounds = {}
        if self.has_base:
            # Show site IDs on the same normalized source that the model reads.
            normalized = ast.parse(rules.inspect_draft(draft)['function'])
            self.reachable_bounds = site_bounds(entry(normalized))
            source = ast.unparse(normalized).splitlines()
            for site, node in returns_in(entry(normalized)).items():
                self.sites[site] = f'{node.lineno}행 {ast.unparse(node)}'
                source[node.lineno-1] += f'  # {site}'
                if isinstance(node.value, ast.Constant) and type(node.value.value) is bool:
                    self.literal_returns[site] = node.value.value
            self.annotated = '\n'.join(source)
        literal = rules.obj({'amount': {'type':'integer'}, 'unit': {'type':'string','enum':list(UNIT_SECONDS)}})
        bound = ({'oneOf': [{'type':'string','enum':list(self.quantities)}, literal]}
                 if self.quantities else literal)
        test = rules.obj({'input':rules.FIELD, 'op':{'type':'string','enum':list(rules.OPS)}, 'bound':bound})
        branch = rules.obj({'at':{'type':'string','enum':list(self.sites)}, 'when':rules.array(test, 1, 4),
                            'allow':rules.BOOL})
        group = rules.obj({'rank':rules.GROUP['properties']['rank'], 'branches':rules.array(branch, 0, 3),
                           'assumption':rules.TEXT})
        self.slots = dict.fromkeys(clauses, group)
        if not self.has_base:
            self.slots[rules.DEFAULT] = rules.BOOL

    def integer_plan(self, plan):
        if not rules.matches(plan, rules.obj(self.slots)):
            raise ValueError('수정 규칙의 수량·항목 형식을 확인하세요.')
        result = copy.deepcopy(plan)
        for key in self.clauses:
            for branch in result[key]['branches']:
                del branch['at']
                for test in branch['when']:
                    bound = test.pop('bound')
                    if isinstance(bound, str):
                        test['seconds'] = self.quantities[bound]['seconds']
                    else:
                        test['seconds'] = bound['amount'] * UNIT_SECONDS[bound['unit']]
        # A dummy last return is discarded when the original function supplies the fallthrough.
        result.setdefault(rules.DEFAULT, False)
        return result

    def render(self, plan):
        translated, lines = rules.render(self.integer_plan(plan), self.clauses)
        if not self.has_base:
            return translated, lines
        lines.pop(rules.DEFAULT)
        prefix = ast.parse(translated).body[0].body[:-1]
        if not prefix:
            return self.draft, lines
        changed = copy.deepcopy(self.tree)
        target = entry(changed)
        original_sites = returns_in(target)
        at_site = {k:[] for k in self.sites}
        inserted_names = {}
        for (key, name, row), node in zip(rules.ordered_branches(plan, self.clauses), prefix):
            at_site[row['at']].append(node)
            inserted_names[id(node)] = (key, name)
        by_node = {id(node):at_site[k] for k,node in original_sites.items()}
        class InsertGuards(ast.NodeTransformer):
            def visit_Return(self, node):
                return [*by_node[id(node)], node] if id(node) in by_node else node
        InsertGuards().visit(target)
        offset = int(ast.get_docstring(target, clean=False) is not None)
        target.body[offset:offset] = at_site['ENTRY']
        emitted = ast.unparse(changed)+'\n'
        reparsed = ast.parse(emitted)
        if ast.dump(changed) != ast.dump(reparsed):
            raise ValueError('출력 함수와 승인된 구문이 일치하지 않습니다.')
        locations = {key: [] for key in self.clauses}
        source = emitted.splitlines()
        for node, actual in zip(ast.walk(changed), ast.walk(reparsed)):
            if id(node) in inserted_names:
                key, name = inserted_names[id(node)]
                locations[key].append(actual.lineno)
                source[actual.lineno-1] += f'  # {name}'
        class RemoveGuards(ast.NodeTransformer):
            def visit_If(self, node):
                return None if id(node) in inserted_names else self.generic_visit(node)
        if ast.dump(RemoveGuards().visit(changed)) != ast.dump(self.tree):
            raise ValueError('수정 대상 밖의 원래 구문이 바뀌었습니다.')
        return '\n'.join(source)+'\n', locations

    def notes(self, plan):
        integers = self.integer_plan(plan)
        by_site = {site:[] for site in self.sites}
        for (_, name, row), (_, _, source) in zip(rules.ordered_branches(integers, self.clauses),
                                                  rules.ordered_branches(plan, self.clauses)):
            by_site[source['at']].append((name, rules.bounds(row['when']), row['allow']))
        notes = {}
        for site, rows in by_site.items():
            if not rows:
                continue
            notes[site] = rules.order_notes((name,box) for name,box,_ in rows)
            for index, (name, box, value) in enumerate(rows):
                if site in self.reachable_bounds and not overlap(box, self.reachable_bounds[site]):
                    notes[site].append(f'{name}: 원래 함수에서 {site}에 도달하는 조건과 양립할 수 없음.')
                if site not in self.literal_returns or value != self.literal_returns[site]:
                    continue
                if not any(v != value and overlap(box,later) for _,later,v in rows[index+1:]):
                    notes[site].append(f'{name}: 이 조건을 제거해도 {site}의 원래 return {value}와 반환값이 같음.')
        return {'branch_order_notes_by_site':notes,
                'fields_by_clause':{k:sorted({t['input'] for b in plan[k]['branches'] for t in b['when']})
                                    for k in self.clauses}}
