"""Run the earlier three-family experiment on two frozen reservation projects."""
import hashlib
import sys
import time
from contextlib import ExitStack
from pathlib import Path

OUT = Path(__file__).resolve().parent
REPO = OUT.parents[1]
sys.path.insert(0, str(REPO))

from experiments import scoped_transfer as pipeline
from experiments.local_transport import local_server, locked_output, read, save
from experiments.project_review import freeze

TASKS = ('reservation', 'calendar')
GROUPS = ('A', 'B', 'C', 'mixed')
WEIGHTS = read(OUT.parent / 'family-100-v1' / 'weights.json')
MODELS = {g: 'var/local-models/' + weight['filename'] for g, weight in WEIGHTS.items()}
PORTS = {model: 18851 + i for i, model in enumerate(MODELS.values())}
pipeline.BANK = OUT / 'public'
TRANSFER = REPO / 'experiments/project-transfer-20261126'
OFFICIAL = REPO / 'reservation_benchmark'
SAMPLE = REPO / 'experiments/pipeline100/sample.json'
CONTROL_FILES = [
    SAMPLE, OFFICIAL/'evaluator/cases.json', OFFICIAL/'evaluator/answer_key.json',
    OFFICIAL/'evaluator/policy.json', OFFICIAL/'evaluator/HUMAN_POLICY.md',
    TRANSFER/'public/reservation.json', TRANSFER/'operator-cards.json',
    REPO/'experiments/festival-mini-20261126/operator-variants.json',
    OFFICIAL/'agent/TASK.md', OFFICIAL/'agent/solution.py',
    REPO/'experiments/scoped_transfer.py', REPO/'backend/allocation_repair.py',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def setup():
    pipeline.BANK.mkdir(exist_ok=True)
    freeze(pipeline.BANK/'reservation.json', read(TRANSFER/'public/reservation.json'))
    freeze(pipeline.BANK/'calendar.json', {
        'brief': (OFFICIAL/'agent/TASK.md').read_text(),
        'files': {'solution.py': (OFFICIAL/'agent/solution.py').read_text()},
    })
    seconds_cards = read(TRANSFER/'operator-cards.json')['reservation']
    seconds_cards.update(read(REPO/'experiments/festival-mini-20261126/operator-variants.json')['reservation'])
    seconds_cards['no_calendar'] = '이 지점은 매일 영업합니다.'
    calendar_cards = {
        'deadline': '일반 취소는 예약 이용 시작 24시간 전까지 가능합니다.',
        'boundary': '일반 취소는 마감 시각과 정확히 같을 때도 허용합니다.',
        'before': '일반 취소는 마감 전에 허용합니다.',
        'past': '일반 취소 마감이 지나면 일반 취소는 거부합니다.',
        'weekdays': '금요일, 토요일, 일요일이 정기 휴무일입니다.',
        'holiday_shift': '기본 마감 날짜가 휴무일이면 그보다 앞선 가장 가까운 영업일 오후 6시로 마감을 당깁니다. 그 영업일을 찾을 때는 추가 휴일도 건너뜁니다.',
        'extra_days': '추가 휴일은 2026년 11월 10일과 2026년 12월 24일입니다.',
        'clock': '예약 직후 정정 시간은 예약을 생성한 때부터 셉니다.',
        'duration': '예약 직후 정정할 수 있는 시간은 10분입니다.',
        'end': '예약 직후 정정은 정확히 10분이 되는 순간에도 가능합니다.',
        'late': '정정 기간 안이면 일반 마감이 지났어도 시작 전에는 취소할 수 있습니다.',
        'start': '현재가 이용 시작과 정확히 같으면 정정 기간이 남아 있어도 취소할 수 없습니다.',
        'after': '이미 이용이 시작된 뒤에는 정정 기간이 남아 있어도 취소할 수 없습니다.',
        'future_booking': '예약 생성 시각이 현재보다 미래이면 거부합니다.',
        'invalid_booking': '예약 생성 시각이 이용 시작 시각과 같거나 그보다 나중이면 거부합니다.',
        'request_day': '취소를 접수한 날이나 이용 날짜 자체가 휴무일이어도 온라인 취소가 가능합니다. 휴무 달력은 마감 계산에 적용합니다.',
        'zone': '날짜와 시각의 정책 기준은 한국 시간인 UTC+09:00입니다.',
        'inputs': '세 시각은 시간대 오프셋이 있는 ISO 8601 문자열입니다. 현재 시각은 첫 번째 입력을 사용합니다.',
        'output': '취소 허용은 참, 거부는 거짓으로 반환합니다.',
    }
    freeze(OUT/'cards.json', {'reservation':seconds_cards, 'calendar':calendar_cards})
    freeze(OUT/'design.json', {
        'models': WEIGHTS, 'tasks': list(TASKS), 'seed':263, 'cycles':3,
        'question_budget_per_cycle':3,
        'conditions':'solo, self, three same-family reviewers for A/B/C; A with A/B/C reviewers',
        'mixed_roles':'[task_index + round_index + role_index] mod 3, all zero-based',
        'oracle':'Codex as delegated owner. Only the sorts of decisions a question explicitly requests are answered from the frozen policy cards. Collect questions per cycle into one natural-language reply. Ask for specificity for unanswerable questions.',
        'scores':'All final submissions locked before independent assessment. Each set scored separately.',
        'source_sha256': {str(p.relative_to(REPO)): digest(p) for p in CONTROL_FILES},
    })
    if not (OUT/'labels.json').exists():
        save(OUT/'labels.json', {})
    (OUT/'calls').mkdir(exist_ok=True)


def question_key(task, question):
    return hashlib.sha256((task+'\n'+question).encode()).hexdigest()[:18]


def outstanding():
    labels = read(OUT/'labels.json')
    cards = read(OUT/'cards.json')
    unknown = {}
    for f in sorted(OUT.glob('runs/*/*/*-questions.json')):
        task = f.parent.name
        questions = read(f)
        if not questions:
            continue
        keys = [question_key(task,q) for q in questions]
        for k,q in zip(keys,questions):
            if k not in labels:
                unknown[k] = (task,q)
        if any(k not in labels for k in keys):
            continue
        selected = {c for k in keys for c in labels[k]}
        if selected - cards[task].keys():
            raise ValueError(f'Unknown policy in answer: {keys}')
        reply = ' '.join(v for c,v in cards[task].items() if c in selected)
        if not reply:
            reply = '질문한 내용에 대해 더 정해진 답을 드리려면, 판단할 예약 상황이나 궁금한 운영 기준을 구체적으로 짚어 주세요.'
        freeze(f.with_name(f.name.replace('questions','reply')), reply)
    return unknown


def run():
    with locked_output(OUT):
        setup()
        with ExitStack() as stack:
            for model,port in PORTS.items():
                stack.enter_context(local_server(port,model))
                print('Ready',model,flush=True)
            sealed = {}
            while len(sealed) != len(TASKS)*len(GROUPS):
                outstanding()
                for group in GROUPS:
                    for i,task in enumerate(TASKS):
                        folder = OUT/'runs'/group/task
                        folder.mkdir(exist_ok=True,parents=True)
                        if not (folder/'calls').exists():
                            (folder/'calls').symlink_to(OUT/'calls',target_is_directory=True)
                        if (folder/'sealed.json').exists():
                            sealed[group+'/'+task] = read(folder/'sealed.json')
                            continue
                        if any(read(f) and not f.with_name(f.name.replace('questions','reply')).exists()
                               for f in folder.glob('*-questions.json')):
                            continue
                        main = MODELS['A' if group=='mixed' else group]
                        schedule = [[main]*3 for _ in range(3)]
                        if group=='mixed':
                            schedule = [[MODELS['ABC'[(i+n+j)%3]] for j in range(3)] for n in range(3)]
                        pipeline.run(task, folder, PORTS[main], model=main, arms=('abc',) if group=='mixed' else ('self','abc'),
                                     reviewer_schedule=schedule, model_ports=PORTS, draft_fallback=True)
                if len(sealed) != len(TASKS)*len(GROUPS):
                    time.sleep(1)
            for task in TASKS:
                assert sealed['mixed/'+task]['solo'] == sealed['A/'+task]['solo']
            freeze(OUT/'sealed-all.json',sealed)
            print('Sealed all 20 submissions (10 conditions on two reservation tasks).',flush=True)


if __name__ == '__main__':
    if sys.argv[1:] == ['pending']:
        for key,(task,q) in outstanding().items():
            print(key,task,q)
    else:
        run()
