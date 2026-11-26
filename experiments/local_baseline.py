"""Run the basic cancellation pilot with one local llama.cpp model and a human operator."""
import argparse
import json
import re
from pathlib import Path

from backend.isolated import grade_isolated
from experiments.local_transport import generate


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / 'reservation_benchmark'
SYSTEM = '당신은 예약 시스템의 Python 개발자입니다. 주어진 안내문과 담당자의 답을 사용하세요.'
ASK = '코드를 쓰기 전에 판정을 바꿀 수 있는 미확정 운영 기준을 담당자에게 한 번에 질문하세요. 필요한 질문만 적고, 없으면 "없음"이라고 하세요.'
IMPLEMENT = '함수를 구현하세요. 답변이 없는 부분은 합리적으로 가정하세요. 표준 라이브러리만 사용하고, 실행 가능한 Python 소스 전체를 하나의 코드 블록으로 반환하세요.'
REVIEW = '같은 개발자로서 방금 작성한 코드를 한 번 자체 검토하세요. 안내문과 담당자의 답변을 다시 읽고, 각 요구사항에 대응하는 코드가 있는지와 경계에서의 동작을 확인하세요. 필요한 부분을 수정하고 전체 Python 소스를 하나의 코드 블록으로 반환하세요.'
SECONDS_CONTRACT = ('작은 연습실의 예약 취소 정책 함수 `allow_cancel(age_seconds, until_start_seconds) -> bool`을 구현하세요. '
                    '두 입력은 정수 초입니다. age_seconds는 예약 생성부터 현재까지 경과한 시간(0 이상), '
                    'until_start_seconds는 이용 시작까지 남은 시간(0은 시작 순간, 음수는 이미 시작)입니다. 시간 변환은 호출자가 처리합니다.')
SECONDS_ADAPTER = '''

def can_cancel(now, booked_at, starts_at):
    from datetime import datetime
    current, booked, starts = map(datetime.fromisoformat, (now, booked_at, starts_at))
    return allow_cancel(int((current - booked).total_seconds()), int((starts - current).total_seconds()))
'''


def submission_text(response):
    blocks = re.findall(r'^```(?:python|py)?[ \t]*\n(.*?)^```[ \t]*$', response, re.M | re.S | re.I)
    return blocks[0] if len(blocks) == 1 else response


def run(args):
    brief = (BENCHMARK / 'agent/TASK_BASIC.md').read_text()
    if args.inputs == 'seconds':
        title, _, policies = brief.split('\n\n', 2)
        brief = '\n\n'.join((title, SECONDS_CONTRACT, policies))
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': brief + '\n\n' + ASK}]
    record = {'task_id': 'cancellation_basic', 'architecture': 'main-only', 'seed': args.seed,
              'endpoint': f'127.0.0.1:{args.port}', 'model_file': args.model_file, 'inputs': args.inputs,
              'status': 'started', 'calls': []}
    if args.thinking is not None:
        record['thinking'] = args.thinking
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as f:
        json.dump(record, f, ensure_ascii=False)
    def save():
        args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    try:
        if args.review_of:
            draft = json.loads(args.review_of.read_text())
            if (draft['model_file'], draft['seed'], draft.get('inputs', 'iso')) != (args.model_file, args.seed, args.inputs):
                raise ValueError('모델, 시드, 입력 조건이 초안과 일치해야 합니다.')
            if draft.get('thinking') != args.thinking:
                raise ValueError('추론 모드가 초안과 일치해야 합니다.')
            if len(draft['calls']) != 2 or draft['status'] != 'scored':
                raise ValueError('두 호출로 작성한 완료된 초안이 필요합니다.')
            record['review_of'] = args.review_of.name
            record['operator_answer'] = draft['operator_answer']
            implementation = draft['calls'][1]
            # Only the original conversation and its response enter the new call.
            messages = implementation['request']['messages'] + [
                {'role': 'assistant', 'content': implementation['text']},
                {'role': 'user', 'content': REVIEW}]
        else:
            questions = generate(args.port, args.model_file, messages, args.seed, 450, args.thinking)
            record['calls'].append(questions)
            save()
            print(questions['text'], flush=True)
            answer = input('고정 답변 카드에서 질문에 해당하는 답을 입력하세요 (질문 없음은 Enter).\n')
            record['operator_answer'] = answer
            messages = messages + [{'role': 'assistant', 'content': questions['text']},
                                   {'role': 'user', 'content': (answer + '\n' if answer else '') + IMPLEMENT}]
        code = generate(args.port, args.model_file, messages, args.seed, 1500, args.thinking)
        record['calls'].append(code)
        source = submission_text(code['text'])
        record['submission'] = source
        if args.inputs == 'seconds':
            record['input_adapter'] = SECONDS_ADAPTER
            source += SECONDS_ADAPTER
        save()
        report = grade_isolated(source, BENCHMARK, 'cancellation_basic')
        record.update(status='scored', report=report)
        print(report['score'], '/', report['total'], report['categories'], flush=True)
    except Exception as exc:
        record.update(status='interrupted', error=str(exc))
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18751)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--inputs', choices=['iso', 'seconds'], default='iso')
    parser.add_argument('--thinking', choices=['off', 'on'], help='Set Qwen3 reasoning mode')
    parser.add_argument('--review-of', type=Path, help='Same main agent checks an existing draft once')
    parser.add_argument('--model-file', required=True, help='Model filename used to start llama-server')
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
