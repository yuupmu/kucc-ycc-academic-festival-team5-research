"""Exploratory same-three-calls comparison and matched complete/partial requirement control."""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from backend.allocation_repair import apply_edits,pending_sites
from backend.structured_output import obj,array
from experiments.festival_protocol import call_model
from experiments.local_transport import compact,local_server,locked_output,read
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING,bound_edits,edit_schema,evidence_choices,VIEWS
from run_pairs import PROMPT,content_hash,sealed_text,sh
BASE=OUT/'review-controls'
MODEL='var/local-models/Qwen3.5-4B-Q4_K_M.gguf'
PORT=18937
BANK=LAB/'experiments/transfer100-20261126'
TASKS=('upload','print')
CAP_REVIEW=1050
CAP_WRITE=1900
ROLE_PROMPT='공개 명세에서 빠지고 서로 다른 운영 기준에 따라 결과가 달라지는 결정 한 가지만 골라 담당자에게 질문하세요. 공개 명세만으로 동작을 정할 수 있다면 빈 문자열을 쓰세요. 구현 방법 또는 이미 명시된 사항은 묻지 마세요.'
REVIEW_SCHEMA=obj({'question':STRING})

def variant_specs():
    for task in TASKS:
        for reg in ('same-calls','total-cap'):
            for arm in ('sequential','independent'):
                yield f'{task}_{reg}_{arm}',dict(task=task,regime=reg,arm=arm,seed=593,doc='original',n=3)
        for seed in (593,811):
            for doc in ('full','missing'):
                yield f'{task}_{doc}_{seed}',dict(task=task,regime='same-calls',arm='main',seed=seed,doc=doc,n=1)

def owner_cards(task):
    return read(LAB/'var/family-100-v1/cards.json')[task]

def argument(spec):
    task=spec['task'];public=read(BANK/'public'/f'{task}.json')['brief']
    draft=(LAB/'var/family-100-v1/runs/A'/task/'submissions/solo/solution.py').read_text()
    if spec['doc']!='original':
        cs=owner_cards(task)
        keys={'upload':['l','z','b'],'print':['w','h','b','z']}[task]
        if spec['doc']=='missing':keys=keys[:-1]
        public=public.rsplit('\n',1)[0]+'\n'+' '.join(cs[k] for k in keys)
        if task=='upload':public+=' 파일 내용이나 확장자는 입력에 없습니다.'
    return public,draft

def post(endpoint,payload):
    req=Request(f'http://127.0.0.1:{PORT}/'+endpoint,json.dumps(payload).encode(),{'Content-Type':'application/json'})
    with build_opener(ProxyHandler({})).open(req,timeout=30) as f:return json.load(f)
def prompt_tokens(system,data):
    messages=[{'role':'system','content':system},{'role':'user','content':compact(data)}]
    text=post('apply-template',dict(messages=messages,enable_thinking=False,chat_template_kwargs={'enable_thinking':False},add_generation_prompt=True))['prompt']
    return len(post('tokenize',dict(content=text,add_special=True,parse_special=True))['tokens'])

def ask(out,role,system,packet,schema,seed,limit,cap):
    estimate=prompt_tokens(system,packet) if cap else None
    if cap:
        limit=min(limit,cap-estimate-16)
        if limit<1:return None,dict(reason='preflight-budget',tokens=0,estimate=estimate,cap=cap)
    key,value=call_model(out,{'model':MODEL},role,system,packet,schema,seed,limit,PORT)
    raw=read(out/'calls'/(key+'.json'))
    total=raw['usage']['total_tokens']
    if cap and total>cap:raise RuntimeError(f'Token cap exceeded {key} {total}>{cap}')
    return value,dict(call=key,tokens=total,estimate=estimate,cap=cap,max_output=limit,
                      prompt_tokens=raw['usage']['prompt_tokens'],completion_tokens=raw['usage']['completion_tokens'],finish=raw['finish_reason'])

def review(port=PORT):
    BASE.mkdir(exist_ok=True)
    controls={}
    for s,v in variant_specs():
        brief,draft=argument(v)
        controls[s]={**v,'brief':brief,'code_sha256':sh(draft.encode())}
    freeze(BASE/'design.json',dict(variants=controls,views=VIEWS,model=MODEL,
           budget='same-calls: each review max 240 output, one edit max 720 output; total-cap: prompt + output per review <=1050, one edit <=1900, total <=5050 including writer; shared archived draft upstream excluded',
           human='up to two distinct requested card items, first-mentioned order, one combined reply, no tests or answers from grading',
           quiz='full versus one omitted policy uses same main question role in both conditions; no code edit or scoring for this question-only control',
           source=content_hash(Path(__file__))))
    if not (BASE/'sealed-questions.json').exists():
        with locked_output(BASE),local_server(PORT,MODEL):
            index={}
            for key,spec in variant_specs():
                pub,code=argument(spec);folder=BASE/key;folder.mkdir(exist_ok=True)
                log=[];questions=[]
                for i in range(spec['n']):
                    pooled=spec['regime']=='total-cap'
                    packet={'brief':pub,'code':code}
                    if spec['arm']=='sequential' and i:packet['previous_reviews']=questions[:]
                    if spec['arm']=='main':
                        system='당신은 메인 작성자입니다. '+ROLE_PROMPT
                    else:
                        system='당신은 이 코드의 검토자입니다. 관점은 '+VIEWS[i]+'입니다. '+ROLE_PROMPT
                    v,record=ask(folder,'policy-review',system,packet,REVIEW_SCHEMA,spec['seed']+i,240,CAP_REVIEW if pooled else None)
                    q=v['question'].strip() if v else ''
                    questions.append(q);log.append({**record,'decoded':v is not None,'question':q})
                freeze(folder/'review.json',log)
                index[key]=content_hash(folder/'review.json')
            freeze(BASE/'sealed-questions.json',index)
    # Only free-text questions and task can be seen during owner coding.
    unique={}
    for key,spec in variant_specs():
        for r in read(BASE/key/'review.json'):
            q=r['question']
            if q:
                ident=sh((spec['task']+'\n'+q).encode())[:16]
                unique[ident]={'task':spec['task'],'question':q}
    freeze(BASE/'blind-questions.json',dict(sorted(unique.items())))
    print('Frozen review protocols',len(controls),'distinct questions',len(unique),flush=True)

def write():
    design=read(BASE/'design.json');assert design['source']==content_hash(Path(__file__))
    seals=read(BASE/'sealed-questions.json')
    labels=read(BASE/'owner-labels.json')
    bank=read(BASE/'blind-questions.json')
    assert set(bank)==set(labels)
    manifest={}
    with locked_output(BASE),local_server(PORT,MODEL):
        for key,spec in variant_specs():
            folder=BASE/key;public,code=argument(spec)
            assert content_hash(folder/'review.json')==seals[key]
            log=read(folder/'review.json')
            selection=[]
            for q in [r['question'] for r in log if r['question']]:
                label=labels[sh((spec['task']+'\n'+q).encode())[:16]]
                for c in label:
                    if c not in selection:selection.append(c)
            selected=selection[:2]
            if spec['arm']=='main':continue
            cs=owner_cards(spec['task'])
            questions=[r['question'] for r in log if r['question']]
            answer='\n'.join(cs[c] for c in selected) if selected else ''
            record=None;edits=[];outcome='no-request'
            if answer:
                history=[dict(request_id='abc-1',questions=questions,answer={'text':answer})]
                choices=evidence_choices(history)
                packet=dict(brief=public,code=code,dialogue=history,review=[],pending=pending_sites(code),evidence=choices)
                fmt=obj({'edits':array(edit_schema(choices),0,6)})
                v,record=ask(folder,'main-edit',PROMPT,packet,fmt,701,720,CAP_WRITE if spec['regime']=='total-cap' else None)
                if v is None:outcome='invalid/budget'
                else:
                    edits=v['edits']
                    try:
                        new=apply_edits(code,bound_edits(v,choices),history,['abc-1'])
                        outcome='applied' if new!=code else 'no-edit'
                        code=new
                    except ValueError as e:outcome='rejected: '+str(e)
            tokens=sum(r['tokens'] for r in log)+(record['tokens'] if record else 0)
            if spec['regime']=='total-cap': assert tokens<=3*CAP_REVIEW+CAP_WRITE
            manifest[key]=sealed_text(folder/'solution.py',code)
            freeze(folder/'submission.json',dict(proposed=selection,selected=selected,answer=answer,record=record,
                   edits=edits,outcome=outcome,tokens=tokens))
        freeze(BASE/'sealed-all.json',{'questions':content_hash(BASE/'sealed-questions.json'),'labels':content_hash(BASE/'owner-labels.json'),
                  'solutions':manifest})
    print('Comparison submissions sealed',len(manifest))
if __name__=='__main__':
    os.chdir(LAB)
    p=argparse.ArgumentParser();p.add_argument('action',choices=('review','write'));args=p.parse_args()
    (review if args.action=='review' else write)()

