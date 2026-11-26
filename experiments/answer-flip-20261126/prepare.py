"""Freeze model-facing state independently from the two post-submission answer keys."""
from pathlib import Path
import hashlib
import json
import sys

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from experiments.local_transport import read
from experiments.project_review import freeze

TASKS = ('reservation', 'upload', 'triage', 'sensors')
SEEDS = (273, 419, 887)
PORT = 18936
MODEL = 'var/local-models/Qwen3.5-4B-Q4_K_M.gguf'
def sha(value):
    return hashlib.sha256(value).hexdigest()
def digest(path):
    return sha(path.read_bytes())
def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    freeze(path, data)
def set_state(task, brief, code, qs, answer, old, new, function, references):
    assert answer.count(old)==1 and new not in answer and old!=new
    arms={'A':answer,'B':answer.replace(old,new,1)}
    assert arms['B'].replace(new,old,1)==answer
    value=dict(task=task,brief=brief,code=code,questions=qs,review=[],function=function,answers=arms,
               changed_sentence={'A':old,'B':new},source_paths={str(p.relative_to(LAB)):digest(p) for p in references})
    save(OUT/'frozen'/f'{task}.json',value)

def states():
    for task in ('reservation','triage'):
        base=LAB/'experiments/pipeline100/runs'/task/'live-multi'
        snapshot=base/'initial/solo/v1/snapshot.json'
        reply=base/'cycle-1/answer.json'
        public=LAB/'experiments/project-transfer-20261126/public'/f'{task}.json'
        data=read(reply)
        if task=='reservation':
            old,new='정정 기간이 정확히 끝나는 순간도 포함합니다.','정정 기간이 정확히 끝나는 순간은 제외합니다.'
            function='allow_cancel'
        else:
            old,new='여러 담당 태그가 있으면 privacy, billing, account 순서로 가장 앞선 팀을 선택합니다.','여러 담당 태그가 있으면 privacy, account, billing 순서로 가장 앞선 팀을 선택합니다.'
            function='triage'
        set_state(task,read(public)['brief'],next(iter(read(snapshot)['files'].values())),
                  [q['question'] for q in data['questions']],data['text'],old,new,function,[snapshot,reply,public])
    d=LAB/'var/family-100-v1/runs/A/upload'
    paths=[d/'design.json',d/'submissions/solo/solution.py',d/'abc-1-questions.json',d/'abc-1-reply.json']
    set_state('upload',read(paths[0])['project']['brief'],paths[1].read_text(),read(paths[2]),read(paths[3]),
              '정확히 상한이면 허용합니다.','정확히 상한이면 거부합니다.','allow_upload',paths)
    # This neutral starter and question are new material, fixed before evaluating the other tasks.
    code="""def sensor_values(readings):
    result = {}
    for sensor, value in readings:
        if sensor in result and result[sensor] != value:
            raise NotImplementedError
        result[sensor] = value
    return result
"""
    brief='sensor_values(readings)는 입력 순서대로 센서 ID(문자열)와 측정값(정수)의 쌍을 읽고 ID별 측정값을 담은 사전을 반환합니다. 빈 입력은 빈 사전입니다. 같은 ID에 같은 값이 반복되면 하나로 합칩니다. 같은 ID의 값들이 다를 때 어떤 값을 보존하는지는 현장 담당자가 정합니다.'
    old,new='같은 센서에 서로 다른 측정값이 들어오면 가장 먼저 받은 값을 보존해 주세요.','같은 센서에 서로 다른 측정값이 들어오면 가장 나중에 받은 값을 보존해 주세요.'
    set_state('sensors',brief,code,['같은 센서 ID에 서로 다른 값이 여러 번 들어올 때, 어느 값을 기록해야 하나요?'],old,old,new,'sensor_values',[])

def expected(task,args,arm):
    if task=='reservation':
        age,left=args
        return left>0 and (left>=86400 or (age<=600 if arm=='A' else age<600))
    if task=='upload':
        size,=args
        return 0<size and (size<=16 if arm=='A' else size<16)
    if task=='triage':
        tags,=args
        rank=('privacy','billing','account') if arm=='A' else ('privacy','account','billing')
        return next((t for t in rank if t in tags),'general')
    result={}
    for key,value in args[0]:
        if key not in result or arm=='B':
            result[key]=value
    return result

def cases():
    probes={
        'reservation':[[age,left] for left in (1,3600,86399,90000,0,-1) for age in (599,600,601)],
        'upload':[[n] for n in (-2,-1,0,1,8,15,16,17,18,999)],
        'triage':[[tags] for tags in (['account','billing'],['billing','account'],['account','misc','billing'],['billing','account','billing'],['account'],['billing'],['privacy'],['account','privacy'],['privacy','billing'],['account','billing','privacy'],['misc','billing'],['account','account'])],
        'sensors':[[r] for r in ([],[['x',1]],[['x',1],['x',1]],[['x',1],['y',2]],[['x',0],['y',0],['x',0]],[['q',-2],['q',-2]],[['x',1],['x',2]],[['x',2],['x',1]],[['x',1],['y',8],['x',3]],[['a',1],['b',2],['a',9],['b',7]],[['s',3],['s',-1],['s',5]],[['x',3],['x',4],['x',3]])]
    }
    result=[]
    def row(task,panel,idx,args):
        return dict(task=task,panel=panel,id=idx,args=args,
                    expected={arm:expected(task,args,arm) for arm in ('A','B')})
    for task,items in probes.items():
        assert len(set(json.dumps(x) for x in items))==len(items)
        result.extend(row(task,'diagnostic',f'{task}-{i:02}',args) for i,args in enumerate(items,1))
    archives=read(LAB/'experiments/pipeline100/sample.json')
    for x in archives:
        task=x['task']
        args=x['inputs'] if task=='reservation' else [x['inputs']]
        r=row(task,'archive',x['id'],args)
        assert r['expected']['A']==x['expected'],r
        result.append(r)
    for x in read(LAB/'experiments/transfer100-20261126/evaluator/cases.json'):
        if x['task']=='upload':
            r=row('upload','archive',x['id'],x['args'])
            assert r['expected']['A']==x['expected'],r
            result.append(r)
    save(OUT/'evaluator/cases.json',result)

if __name__=='__main__':
    states()
    cases()
    artifacts=[*(OUT/'frozen').glob('*.json'),OUT/'evaluator/cases.json',OUT/'prepare.py',OUT/'run_pairs.py',OUT/'score_pairs.py',
               LAB/'backend/allocation_repair.py', LAB/'experiments/festival_protocol.py',LAB/'experiments/scoped_transfer.py',LAB/'experiments/local_transport.py',LAB/'var/family-100-v1/weights.json']
    save(OUT/'design.json',dict(model=MODEL,weights=read(LAB/'var/family-100-v1/weights.json')['A'],tasks=TASKS,seeds=SEEDS,
         rounds=1,scope='fixed first owner reply; no later owner turns or performance feedback',temperature=.3,top_p=.9,top_k=40,thinking=False,
         retries='same writer, 1100/1800 if truncated or malformed, and at most one retry on edit format errors, no tests',
         outcomes='strict paired match on affected inputs; both same, both correct, preservation among initially correct on invariant inputs; decline and error separate',
         design_order='all four tasks, policies, probes, programs and alternate A/B execution order frozen before first model call. Three archived snapshots and one new neutral starter.',
         signatures={str(p.relative_to(LAB)):digest(p) for p in artifacts}))

