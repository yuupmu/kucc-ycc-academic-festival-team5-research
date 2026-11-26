"""Use named source locations and explicit Python operations in the three-cycle writer."""
import argparse
import ast
from pathlib import Path

from backend.structured_output import array, obj
from experiments import scoped_transfer_v2 as pipeline
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import BANK, STRING, edit_schema


VERSION = 'named-operations-v1'
FILL = (
    '표시된 자리 각각에 도달했을 때 해야 할 동작을 고르세요. 근거는 공개 명세와 담당자 회신이고 '
    'behavior는 작성자가 정리한 메모입니다. 초안의 주석에는 답을 받기 전의 가정이 있습니다. '
    'return의 body에는 그 자리로 들어올 모든 입력에서 올바른 값을 주는 파이썬 식 하나만 쓰세요. '
    '불리언이면 참인 입력의 조건이 곧 반환식입니다. continue는 이번 반복의 나머지를 건너뛰고 다음 항목을 처리합니다. '
    'break는 반복을 끝냅니다. 이 두 동작과 keep에는 빈 body를 씁니다. '
    'block은 여러 실행문이 꼭 필요한 경우입니다. 변수 정의만으로 반환값을 대신할 수 없습니다. '
    '근거가 부족하면 keep을 고르세요. 각 자리의 evidence에는 실제 회신을 고르세요. '
    '표시된 자리 이외의 기존 코드까지 수정할 근거가 있을 때만 other_edits를 쓰세요.'
)


def site_context(source, pending):
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    nodes = {(n.lineno, n.col_offset): n for n in ast.walk(tree) if isinstance(n, (ast.Raise, ast.Pass))}
    lines = source.splitlines()
    sites = {}
    for key in sorted(pending, key=lambda k: tuple(map(int, k.split(':')[1:]))):
        _, line, column = key.split(':')
        node = nodes[(int(line), int(column))]
        frames = []
        in_loop = False
        child = node
        while child in parents:
            parent = parents[child]
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                break
            if isinstance(parent, ast.If):
                condition = ast.unparse(parent.test)
                frames.append(condition if child in parent.body else f'not ({condition})')
            if isinstance(parent, (ast.For, ast.AsyncFor, ast.While)) and child in parent.body:
                in_loop = True
            child = parent
        sites[key] = dict(line=int(line), within=list(reversed(frames)), in_loop=in_loop,
                          following=lines[node.end_lineno:node.end_lineno+3])
    return sites


def replacement(choice):
    form, body = choice['form'], choice['body'].strip()
    if form == 'keep':
        return None
    if form in ('continue', 'break'):
        return form
    if form == 'return':
        expression = ast.parse(body, mode='eval').body
        return 'return ' + ast.unparse(expression)
    if not body:
        raise ValueError('Empty block')
    return body


def with_sites(transport):
    def call(out, design, role, prompt, packet, schema, seed, limit, port):
        if role != 'main-edit' or not packet.get('pending'):
            return transport(out, design, role, prompt, packet, schema, seed, limit, port)
        sites = site_context(packet['code'], packet['pending'])
        choices = packet['evidence']
        fields = {}
        for name, site in sites.items():
            forms = ['return', 'block', 'keep']
            if site['in_loop']:
                forms = ['continue', 'block', 'return', 'break', 'keep']
            fields[name] = obj({'evidence': {'type':'string', 'enum':list(choices)},
                                'form': {'type':'string', 'enum':forms}, 'body': STRING})
        fmt = obj({'sites':obj(fields), 'other_edits':array(edit_schema(choices), 0, 6)})
        key, result = transport(out, design, 'main-fill', FILL, dict(packet, sites=sites),
                                fmt, seed, limit, port)
        if result is None:
            return key, None
        edits = []
        try:
            for name, choice in result['sites'].items():
                after = replacement(choice)
                if after is not None:
                    edits.append(dict(evidence=choice['evidence'], before=name, after=after))
        except (SyntaxError, ValueError, RecursionError):
            return key, None
        return key, {'edits': edits + result['other_edits']}
    return call


def run(project, out, port, *, transport=call_model, **options):
    out.mkdir(exist_ok=True, parents=True)
    method = out / 'edit-method.json'
    if (out / 'design.json').exists() and not method.is_file():
        raise ValueError('기존 실험과 다른 편집 방식입니다. 새 실행 폴더를 지정하세요.')
    freeze(method, {'writer': VERSION})
    return pipeline.run(project, out, port, transport=with_sites(transport), **options)


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
