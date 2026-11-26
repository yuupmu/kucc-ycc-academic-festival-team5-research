"""Preserve exact owner-mentioned values while compiling a scalar Boolean decision."""
import argparse
import ast
from pathlib import Path
import re

from backend.structured_output import obj
from experiments import guarded_reply as guards
from experiments import scoped_transfer_v2 as pipeline
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import BANK


VERSION = 'scalar-boolean-points-v1'
POINTS = ('공개 명세와 실제 담당자 회신만 보고 입력값 각각에서 함수가 반환해야 할 값을 고르세요. '
          'True, False, 미정 중 하나입니다. 주어진 내용으로 결정되지 않는 입력에는 미정을 선택하세요.')


def explicit_points(packet):
    brief = packet['brief']
    if not (re.search(r'정수|\binteger\b|:\s*int\b',brief,re.I) and
            re.search(r'->\s*bool(?![a-z0-9_])|\bboolean(?![a-z0-9_])|불리언', brief, re.I)):
        return []
    words = '\n'.join([brief, *(r['answer']['text'] for r in packet['dialogue'])])
    numerals = re.findall(r'(?<![A-Za-z0-9_.])(?<!\d,)[+-]?[0-9]+(?![A-Za-z0-9_]|[.,][0-9])', words)
    values = sorted({int(n) for n in numerals if len(n.lstrip('+-')) <= 16})
    return values if 0 < len(values) <= 8 else []


def normalize(text):
    # In this comparison-only notation a standalone equals sign means equality.
    # Assignment, calls and attributes still fail the predicate parser.
    return re.sub(r'(?<![<>=!:])=(?!=)', '==', text)


def reconcile(result, packet):
    name = packet['parameter']
    yes, no = (normalize(result[k]) for k in ('true_when','false_when'))
    try:
        expression = guards.total_guard(yes, no, name)
    except (SyntaxError, ValueError, RecursionError):
        expression = None
    if expression is None:
        return dict(result, true_when='False', false_when='False')
    trees = [ast.parse(v, mode='eval').body for v in (expression, no.strip())]
    boundaries = set()
    for tree in trees:
        for parent in ast.walk(tree):
            if isinstance(parent, ast.Compare):
                for operand in (parent.left,*parent.comparators):
                    if not isinstance(operand, ast.Name):
                        boundaries.add(guards.term(operand, name, 0))
    patches = []
    for row in packet['behavior']:
        if not re.fullmatch(r'-?\d+', row['when']):
            continue
        point = int(row['when'])
        if point not in boundaries:
            continue
        if row['then'] not in ('True','False'):
            return dict(result, true_when='False', false_when='False')
        wanted = row['then'] == 'True'
        if guards.check_predicate(trees[0], name, point) != wanted:
            patches.append((point, wanted))
    for point, wanted in patches:
        expression = (f'({expression}) or {name} == {point}' if wanted else
                      f'({expression}) and {name} != {point}')
    return dict(result, true_when=expression, false_when=f'not ({expression})')


def with_points(transport):
    def call(out, design, role, prompt, packet, schema, seed, limit, port):
        if role == 'main-behavior':
            numbers = explicit_points(packet)
            if numbers:
                fmt = obj({str(n):{'type':'string','enum':['True','False','미정']} for n in numbers})
                key, decisions = transport(out, design, 'main-point-values', POINTS, dict(packet, inputs=numbers),
                                           fmt, seed, limit, port)
                return key, None if decisions is None else {'behavior':[{'when':str(n), 'then':decisions[str(n)]} for n in numbers]}
        key, result = transport(out, design, role, prompt, packet, schema, seed, limit, port)
        if role == 'main-predicates' and result is not None:
            result = reconcile(result, packet)
        return key, result
    return guards.with_guards(call)


def run(project, out, port, *, transport=call_model, **options):
    out.mkdir(exist_ok=True, parents=True)
    method = out / 'edit-method.json'
    if (out / 'design.json').exists() and not method.is_file():
        raise ValueError('새 편집 방식은 새 실행 폴더에서 시작하세요.')
    freeze(method, {'writer':VERSION})
    return pipeline.run(project, out, port, transport=with_points(transport), **options)


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
    public = read(path if path.is_file() else BANK / (args.project + '.json'))
    with locked_output(args.out):
        if args.answer_file:
            pipeline.receive(args.out, args.reply_to, args.answer_file.read_text())
        with local_server(args.port, MODEL):
            waiting = run(public, args.out, args.port)
    print('담당자 회신 대기 ' + ', '.join(waiting) if waiting else '제출 고정 완료')
