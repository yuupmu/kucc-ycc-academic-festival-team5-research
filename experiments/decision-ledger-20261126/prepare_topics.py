"""Freeze the incoming mixed-review handoff before opening any owner replies."""
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from backend.structured_output import array, obj
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING, VIEWS
from experiments.scoped_transfer_v2 import DRAFT, REVIEW

ARCHIVE = OUT.parent/'mixed-upload-three-answers-writer-20261126'
SETTINGS = read(LAB/'var/family-100-v1/runs/mixed/upload/design.json')
PORT = 18984
TRANSFER = {
    'brief': '공부방 환풍기 제어 함수 run_fan(co2_high: bool, quiet_time: bool) -> bool을 작성하세요. '
             'True를 반환하면 환풍기를 켜고 False를 반환하면 끕니다. 두 입력은 각각 이산화탄소 농도가 높다는 신호와 정숙 시간이라는 신호입니다. '
             '높은 농도 신호만 있으면 환풍기를 켭니다. 정숙 시간 신호만 있으면 환풍기를 끕니다. '
             '두 신호가 동시에 들어왔을 때의 우선순위와 두 신호가 모두 없을 때의 기본 운전 여부는 각각 시설 담당자가 정합니다.',
    'files': {'solution.py': 'def run_fan(co2_high: bool, quiet_time: bool) -> bool:\n    raise NotImplementedError\n'},
}


def run():
    upload = read(ARCHIVE/'unmentioned/input.json')
    freeze(OUT/'upload.json', {k: upload[k] for k in ('brief','code','review')} |
           {'questions': upload['dialogue'][0]['questions']})
    freeze(OUT/'fan-public.json', TRANSFER)
    calls, questions, issues = [], [], []
    for i, model in enumerate(SETTINGS['reviewer_schedule'][0]):
        with local_server(PORT, model):
            if i == 0:
                key, result = call_model(OUT, {'model': model}, 'main', DRAFT, TRANSFER,
                                        obj({'code': STRING}), SETTINGS['seed'], 1100, PORT)
                calls.append(key)
                code = result['code']
                compile(code, 'solution.py', 'exec')
            key, result = call_model(OUT, {'model': model}, 'observer-'+'ABC'[i],
                '당신은 독립 감시자입니다. '+VIEWS[i]+REVIEW, dict(brief=TRANSFER['brief'], code=code, dialogue=[]),
                obj({'questions': array(STRING,0,1), 'issue': STRING}), SETTINGS['seed']+10+i, 1100, PORT)
            calls.append(key)
            if result is not None:
                questions.extend(q.strip() for q in result['questions'] if q.strip())
                if result['issue'].strip():
                    issues.append(result['issue'])
    freeze(OUT/'fan.json', dict(brief=TRANSFER['brief'], code=code, questions=list(dict.fromkeys(questions)),
                                 review=issues, calls=calls))


if __name__=='__main__':
    with locked_output(OUT):
        run()
