"""Compile owner-supported integer decision regions into pending Boolean return sites."""
import argparse
import ast
import operator
from pathlib import Path
import re

from backend.structured_output import obj
from experiments import scoped_transfer_v2 as pipeline
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import BANK, STRING


VERSION = 'scalar-boolean-guards-v1'
DIRECT = '직접 받은 답변에 따라 코드의 필요한 위치만 수정하세요. 미구현 위치는 pending의 키를 before로 쓰고 after에 그 위치에 넣을 실행문만 적으세요. 다른 수정은 원본의 정확한 부분을 before로 인용하세요. evidence에서 근거가 되는 답변을 선택하세요. 답변으로 확정할 수 없는 동작을 만들지 마세요. 이미 맞으면 빈 edits를 반환하세요.'
GUARDS = (
    '담당자 회신과 공개 명세가 설명하는 함수의 값을 입력 범위로 옮기세요. '
    'true_when에는 결과가 True인 정수 전체의 조건, false_when에는 결과가 False인 정수 전체의 조건을 '
    '서로 독립된 파이썬 비교식으로 적으세요. parameter에 적힌 이름과 정수, 비교 연산, and/or/not만 사용하세요. '
    '근거가 없는 입력은 양쪽 식에서 제외하세요. 해당하는 입력이 하나도 없으면 False라고 쓰세요. '
    'return문은 쓰지 마세요. evidence에는 사용한 담당자 회신을 고르세요.'
)
OPS = {ast.Lt:operator.lt, ast.LtE:operator.le, ast.Eq:operator.eq, ast.NotEq:operator.ne,
       ast.GtE:operator.ge, ast.Gt:operator.gt}


def scalar_parameter(packet):
    if not packet['pending'] or packet['review'] or len(packet['evidence']) != 1:
        return None
    tree = ast.parse(packet['code'])
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return None
    fn = tree.body[0]
    args = fn.args
    parameters = args.posonlyargs + args.args
    if len(parameters) != 1 or args.kwonlyargs or args.vararg or args.kwarg or fn.decorator_list:
        return None
    argument = parameters[0]
    if argument.annotation is not None:
        if not isinstance(argument.annotation, ast.Name) or argument.annotation.id != 'int':
            return None
    elif not re.search(r'정수|\binteger\b|:\s*int\b', packet['brief'], re.I):
        return None
    if fn.returns is not None and (not isinstance(fn.returns, ast.Name) or fn.returns.id != 'bool'):
        return None
    returns = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Return):
            if not isinstance(n.value, ast.Constant) or type(n.value.value) is not bool:
                return None
            returns.append(n)
        elif isinstance(n, ast.stmt) and n is not fn and not isinstance(n, (ast.If, ast.Raise, ast.Pass)):
            if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)):
                return None
        if isinstance(n, ast.If):
            try:
                check_predicate(n.test, argument.arg)
            except ValueError:
                return None
    if not returns and not (fn.returns is not None or re.search(r'->\s*bool\b',packet['brief'])):
        return None
    return argument.arg


def term(node, name, number):
    if isinstance(node, ast.Name) and node.id == name:
        return number
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        if isinstance(node.operand, ast.Constant) and type(node.operand.value) is int:
            return node.operand.value if isinstance(node.op, ast.UAdd) else -node.operand.value
    raise ValueError('Only the input and integer literals are supported')


def check_predicate(node, name, number=0):
    if isinstance(node, ast.Constant) and type(node.value) is bool:
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not check_predicate(node.operand, name, number)
    if isinstance(node, ast.BoolOp):
        parts = [check_predicate(v,name,number) for v in node.values]
        return all(parts) if isinstance(node.op, ast.And) else any(parts)
    if isinstance(node, ast.Compare) and all(type(op) in OPS for op in node.ops):
        values = [term(v,name,number) for v in [node.left,*node.comparators]]
        return all(OPS[type(op)](a,b) for op,a,b in zip(node.ops, values, values[1:]))
    raise ValueError('Unsupported Boolean predicate')


def total_guard(yes, no, name):
    expressions = [ast.parse(v.strip(), mode='eval').body for v in (yes,no)]
    # Supported comparisons can change truth only at an integer literal. Each literal and both
    # adjacent atoms represent the entire integer line, including both unbounded tails.
    atoms = {0}
    for expr in expressions:
        check_predicate(expr, name)
        for part in ast.walk(expr):
            if isinstance(part, (ast.Constant, ast.UnaryOp)):
                try:
                    value = term(part, name, 0)
                except ValueError:
                    continue
                atoms.update((value-1, value, value+1))
    if any(check_predicate(expressions[0], name, v) == check_predicate(expressions[1], name, v) for v in atoms):
        return None
    return ast.unparse(expressions[0])


def with_guards(transport):
    def call(out, design, role, prompt, packet, schema, seed, limit, port):
        if role != 'main-edit':
            return transport(out, design, role, prompt, packet, schema, seed, limit, port)
        name = scalar_parameter(packet)
        if name is None:
            direct = {k:packet[k] for k in ('brief','code','dialogue','review','pending','evidence')}
            if 'edit_format_feedback' in packet:
                direct['edit_format_feedback'] = packet['edit_format_feedback']
            return transport(out, design, role, DIRECT, direct, schema, seed, limit, port)
        fmt = obj({'true_when':STRING, 'false_when':STRING,
                   'evidence':{'type':'string', 'enum':list(packet['evidence'])}})
        public = {k:packet[k] for k in ('brief','dialogue','evidence')}
        public.update(parameter=name, behavior=packet.get('behavior', []))
        key, result = transport(out, design, 'main-predicates', GUARDS, public, fmt, seed, limit, port)
        if result is None:
            return key, None
        try:
            expr = total_guard(result['true_when'], result['false_when'], name)
        except (SyntaxError, ValueError, RecursionError):
            expr = None
        edits = [] if expr is None else [
            dict(evidence=result['evidence'], before=slot, after='return ' + expr) for slot in packet['pending']]
        return key, {'edits':edits}
    return call


def run(project, out, port, *, transport=call_model, **options):
    out.mkdir(exist_ok=True, parents=True)
    method = out / 'edit-method.json'
    if (out / 'design.json').exists() and not method.is_file():
        raise ValueError('기존 실행은 원래 방식으로 재생하세요. 새 조건은 새 폴더에서 시작하세요.')
    freeze(method, {'writer':VERSION})
    return pipeline.run(project, out, port, transport=with_guards(transport), **options)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='공개 과제 이름 또는 공개 명세 JSON 경로')
    parser.add_argument('out', type=Path)
    parser.add_argument('--port', type=int, default=18955)
    parser.add_argument('--reply-to')
    parser.add_argument('--answer-file', type=Path)
    args = parser.parse_args()
    if bool(args.reply_to) != bool(args.answer_file):
        parser.error('--reply-to와 --answer-file을 함께 지정하세요.')
    path = Path(args.project)
    project = read(path if path.is_file() else BANK / (args.project + '.json'))
    with locked_output(args.out):
        if args.answer_file:
            pipeline.receive(args.out, args.reply_to, args.answer_file.read_text())
        with local_server(args.port, MODEL):
            waiting = run(project, args.out, args.port)
    print('담당자 회신 대기 ' + ', '.join(waiting) if waiting else '제출 고정 완료')
