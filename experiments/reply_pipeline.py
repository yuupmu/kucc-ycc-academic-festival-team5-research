"""Three owner-mediated cycles; compile the two grounded regions of eligible Boolean functions."""
import argparse
from pathlib import Path
import re

from experiments import guarded_reply as guards, scoped_transfer_v2 as pipeline
from experiments.festival_protocol import MODEL, call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import BANK


VERSION = 'scalar-boolean-guards-equality-v1'
MATH_EQUALITY = re.compile(r'(?<![<>=!:])=(?!=)')


def with_guards(transport):
    def accept_math_equality(out, design, role, prompt, packet, schema, seed, limit, port):
        key, response = transport(out, design, role, prompt, packet, schema, seed, limit, port)
        if role == 'main-predicates' and response is not None:
            response = dict(response, true_when=MATH_EQUALITY.sub('==', response['true_when']),
                            false_when=MATH_EQUALITY.sub('==', response['false_when']))
        return key, response
    return guards.with_guards(accept_math_equality)


def run(project, out, port, *, transport=call_model, **options):
    out.mkdir(exist_ok=True, parents=True)
    method = out / 'edit-method.json'
    if (out / 'design.json').exists() and not method.is_file():
        raise ValueError('기존 실험은 원래 방식으로 재생하세요. 새 버전은 새 실행 폴더에서 시작하세요.')
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
    public = read(path if path.is_file() else BANK / (args.project + '.json'))
    with locked_output(args.out):
        if args.answer_file:
            pipeline.receive(args.out, args.reply_to, args.answer_file.read_text())
        with local_server(args.port, MODEL):
            waiting = run(public, args.out, args.port)
    print('담당자 회신 대기 ' + ', '.join(waiting) if waiting else '제출 고정 완료')
