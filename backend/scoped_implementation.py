"""Source-scoped edits and evidence receipts, independent of any benchmark or policy vocabulary."""
import ast
import io
import re
import textwrap
import tokenize
from collections import defaultdict

from backend import project_syntax


def targets(files, starter):
    result = {}
    for path, source in files.items():
        lines = source.splitlines()
        functions = []
        if path.endswith(('.py', '.pyw')):
            try:
                body = ast.parse(source).body
            except (SyntaxError, ValueError, RecursionError):
                body = []
            kinds = (ast.FunctionDef, ast.AsyncFunctionDef)
            for node in body:
                if isinstance(node, kinds):
                    functions.append((node.name, node))
                if isinstance(node, ast.ClassDef):
                    functions.extend((node.name + '.' + item.name, item) for item in node.body if isinstance(item, kinds))
        for name, node in functions:
            first = node.body[0]
            if (ast.get_docstring(node, clean=False) is not None and len(node.body) > 1 and
                    ast.get_source_segment(source, first) in starter.get(path, '')):
                first = node.body[1]
            if first.lineno == node.lineno or any(
                    s.lineno < first.lineno and s.end_lineno == first.lineno for s in node.body):
                continue
            line = lines[first.lineno - 1]
            prefix = line[:len(line) - len(line.lstrip())]
            args = node.args
            params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            params.extend(a.arg for a in (args.vararg, args.kwarg) if a)
            result[f'T{len(result)+1}'] = dict(path=path, name=name, start=first.lineno-1, end=node.end_lineno,
                prefix=prefix, unit='\t' if '\t' in prefix else ' ' * max(1, len(prefix) - node.col_offset),
                parameters=params, kind='body', signature=ast.unparse(node.args))
        result[f'T{len(result)+1}'] = dict(path=path, name=path, start=0, end=len(lines), prefix='', unit='    ',
                                          parameters=[], kind='file', signature='')
    return result


def natural_edit(key, region, response, evidence):
    if not response:
        raise ValueError('코드 응답이 완성되지 않음')
    fences = re.findall(r'(?ms)^[ \t]*`{3,}[^\r\n]*\r?\n(.*?)^[ \t]*`{3,}[ \t]*\r?$',response)
    if len(fences)>1:
        raise ValueError('한 대상에 서로 다른 코드 블록을 여러 개 반환함')
    text = fences[0] if fences else response
    if region['kind']=='body':
        tree = ast.parse(textwrap.dedent(text))
        defs = [n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
        if defs:
            if len(tree.body)!=1 or len(defs)!=1 or defs[0].name!=region['name'].split('.')[-1]:
                raise ValueError('요청한 함수 범위 밖의 선언')
            fn = defs[0]
            a = fn.args
            args = [v.arg for v in (*a.posonlyargs,*a.args,*a.kwonlyargs)] + [v.arg for v in (a.vararg,a.kwarg) if v]
            if args!=region['parameters']:
                raise ValueError('원본과 인자명이 다름')
            first = fn.body[1] if len(fn.body)>1 and ast.get_docstring(fn,clean=False) is not None else fn.body[0]
            source = textwrap.dedent(text).splitlines()
            text = (ast.get_source_segment(textwrap.dedent(text),first) if first.lineno==fn.lineno and len(fn.body)==1
                    else textwrap.dedent('\n'.join(source[first.lineno-1:fn.end_lineno])))
        else:
            text = textwrap.dedent(text)
    physical = text.splitlines()
    locations = {}
    if region['path'].endswith(('.py','.pyw')):
        try:
            for token in tokenize.generate_tokens(io.StringIO(text).readline):
                if token.type!=tokenize.COMMENT:
                    continue
                marker = re.fullmatch(r'#\s*\[([\w.,\s]+)\]\s*',token.string)
                if marker:
                    ids = re.findall(r'[A-Za-z]\w*(?:\.\d+)*',marker[1])
                    if not ids or set(ids)-evidence.keys():
                        raise ValueError('미수신 근거 번호를 인용함')
                    locations[token.start[0]] = list(dict.fromkeys(ids))
                    physical[token.start[0]-1] = physical[token.start[0]-1][:token.start[1]].rstrip()
        except (tokenize.TokenError,IndentationError) as err:
            raise ValueError('코드의 들여쓰기나 괄호가 유효하지 않음') from err
    return {'target':key,'lines':[{'depth':0,'code':s,'sources':locations.get(i,[])} for i,s in enumerate(physical,1)]}


def names_in(expr):
    return {node.id for node in ast.walk(expr) if isinstance(node, ast.Name)} if expr is not None else set()


def behavior(source):
    """Reachable Python statements, with inputs used directly, by local aliases, or by their enclosing guard."""
    tree = ast.parse(source)
    result = {}
    def visit(block, enclosing, bindings):
        controls = set(enclosing)
        for node in block:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(node.body, set(), {})
                continue
            if isinstance(node,(ast.Pass,ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal)) or (
                    isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):
                continue
            expr = (node.test if isinstance(node,(ast.If,ast.While)) else node.iter if isinstance(node,(ast.For,ast.AsyncFor))
                    else getattr(node,'value',None) or getattr(node,'exc',None))
            direct = names_in(expr)
            used = controls | direct | {origin for name in direct for origin in bindings.get(name, ())}
            result[node.lineno] = sorted(used)
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                for target in (node.targets if isinstance(node,ast.Assign) else [node.target]):
                    for variable in names_in(target):
                        bindings[variable] = used
            if isinstance(node,(ast.For,ast.AsyncFor)):
                for variable in names_in(node.target):
                    bindings[variable] = used
            if isinstance(node,ast.If):
                left, right = bindings.copy(), bindings.copy()
                condition = node.test.value if isinstance(node.test,ast.Constant) else None
                a = visit(node.body,used,left) if condition is None or bool(condition) else False
                b = visit(node.orelse,used,right) if condition is None or not bool(condition) else False
                for name in left.keys() | right.keys():
                    bindings[name] = set(left.get(name, ())) | set(right.get(name, ()))
                if a and b or (condition is not None and (a if condition else b)):
                    return True
                if a or b:
                    controls |= used
            else:
                for child in ('body','orelse','finalbody'):
                    nested = getattr(node, child, None)
                    if isinstance(nested,list):
                        visit(nested,used,bindings.copy())
                for handler in getattr(node, 'handlers', []):
                    visit(handler.body, used, bindings.copy())
                for case in getattr(node, 'cases', []):
                    visit(case.body, used, bindings.copy())
            if isinstance(node,(ast.Return,ast.Raise,ast.Continue,ast.Break)):
                return True
        return False
    visit(tree.body, set(), {})
    return result


def apply(files, regions, edits, decisions):
    grouped = defaultdict(list)
    seen = set()
    for edit in edits:
        key = edit['target']
        if key not in regions or key in seen:
            raise ValueError('중복되거나 원본에 없는 편집 대상')
        seen.add(key)
        grouped[regions[key]['path']].append((key,regions[key],edit['lines']))
    candidate = files.copy()
    annotations = []
    for path, parts in grouped.items():
        if len(parts)>1 and any(r['kind']=='file' for _,r,_ in parts):
            raise ValueError('같은 파일 전체와 그 안의 함수를 동시에 편집함')
        source = files[path]
        original = source.splitlines(keepends=True)
        newline = '\r\n' if '\r\n' in source else '\n'
        written, previous = [], 0
        for key, region, lines in sorted(parts,key=lambda item:item[1]['start']):
            if region['start'] < previous:
                raise ValueError('겹치는 편집 범위')
            written.extend(original[previous:region['start']])
            for row in lines:
                code = row['code']
                if '\n' in code or '\r' in code:
                    raise ValueError('한 행에 여러 물리적 줄이 들어옴')
                if set(row['sources']) - decisions.keys():
                    raise ValueError('존재하지 않는 근거')
                written.append((region['prefix'] + region['unit']*row['depth'] + code if code else '') + newline)
                annotations.append({'target':key, 'file':path, 'line':len(written), 'sources':row['sources']})
            previous = region['end']
        written.extend(original[previous:])
        candidate[path] = ''.join(written)
        if candidate[path].endswith(newline) and source and not source.endswith(('\r','\n')):
            candidate[path] = candidate[path][:-len(newline)]
        if project_syntax.check(path,candidate[path]) == 'invalid':
            raise ValueError('생성한 파일의 구문이 잘못됨')
    maps = {path:behavior(source) for path,source in candidate.items() if path in grouped and path.endswith(('.py','.pyw'))}
    receipts = {}
    for source_id, rule in decisions.items():
        signal = rule['input']
        linked = [item for item in annotations if source_id in item['sources']]
        checked = []
        for item in linked:
            inputs = maps.get(item['file'],{}).get(item['line'])
            checked.append({**item,'inputs':inputs,'reachable_statement':inputs is not None,
                            'input_referenced':inputs is not None and (signal == 'none' or signal in inputs)})
        receipts[source_id] = {'status':rule['status'], 'input':signal, 'locations':checked,
                               'structural_support':any(x['input_referenced'] for x in checked)}
    return candidate, receipts
