"""Run the frozen paired writer on loopback; no evaluator or test access in requests."""
import hashlib
import os
from pathlib import Path
import sys

OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from backend.allocation_repair import apply_edits, pending_sites
from backend.structured_output import array, obj
from experiments.festival_protocol import call_model
from experiments.local_transport import compact, local_server, locked_output, read
from experiments.scoped_transfer import bound_edits, edit_schema, evidence_choices
from experiments.project_review import freeze

PROMPT='직접 받은 답변에 따라 코드의 필요한 위치만 수정하세요. 미구현 위치는 pending의 키를 before로 쓰고 after에 그 위치에 넣을 실행문만 적으세요. 다른 수정은 원본의 정확한 부분을 before로 인용하세요. evidence에서 근거가 되는 답변을 선택하세요. 답변으로 확정할 수 없는 동작을 만들지 마세요. 이미 맞으면 빈 edits를 반환하세요.'
def sh(data):
    return hashlib.sha256(data).hexdigest()
def content_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for buf in iter(lambda:f.read(8388608),b''):
            h.update(buf)
    return h.hexdigest()
def sealed_text(path,text):
    data=text.encode()
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('Published source changed')
    else:
        path.write_bytes(data)
    return sh(data)

def edit(out, model, state, answer, seed, port):
    source=state['code']
    history=[dict(request_id='abc-1',questions=state['questions'],answer={'text':answer})]
    choices=evidence_choices(history)
    packet=dict(brief=state['brief'],code=source,dialogue=history,review=state['review'],
                pending=pending_sites(source),evidence=choices)
    fmt=obj({'edits':array(edit_schema(choices),0,6)})
    attempts=[]
    for retry in range(2):
        response=None
        for limit in (1100,1800):
            key,response=call_model(out,{'model':model},'main-edit',PROMPT,packet,fmt,seed+retry,limit,port)
            attempts.append(dict(call=key,limit=limit,seed=seed+retry,decoded=response is not None))
            if response is not None:break
        if response is None:
            attempts[-1]['outcome']='invalid-output'
            return source, attempts
        edits=response['edits']
        try:
            updated=apply_edits(source,bound_edits(response,choices),history,['abc-1'])
            attempts[-1]['outcome']='applied' if source!=updated else 'no-edit'
            attempts[-1]['edits']=edits
            return updated,attempts
        except ValueError as exc:
            attempts[-1].update(outcome='rejected',reason=str(exc),edits=edits)
            packet['edit_format_feedback']=str(exc)
    return source,attempts

def main():
    os.chdir(LAB)
    design=read(OUT/'design.json')
    for path,signature in design['signatures'].items():
        # The frozen evaluator is checked by the offline scorer, never opened in the writer.
        if '/evaluator/' not in path and not path.endswith(('score_pairs.py','prepare.py')):
            assert content_hash(LAB/path)==signature,path
    model=design['model']
    assert content_hash(LAB/model)==design['weights']['sha256']
    with locked_output(OUT),local_server(18936,model):
        seals={}
        for idx,task in enumerate(design['tasks']):
            state=read(OUT/'frozen'/f'{task}.json')
            common={k:state[k] for k in ('task','brief','code','questions','review','function')}
            common_digest=sh(compact(common).encode())
            for j,seed in enumerate(design['seeds']):
                sides=('A','B') if (idx+j)%2==0 else ('B','A')
                for arm in sides:
                    short=f'{task}/{seed}/{arm}'
                    out=OUT/'runs'/short
                    out.mkdir(parents=True,exist_ok=True)
                    source,attempts=edit(out,model,state,state['answers'][arm],seed,18936)
                    seals[short]=sealed_text(out/'solution.py',source)
                    raw=[read(out/'calls'/(a['call']+'.json')) for a in attempts]
                    freeze(out/'submission.json',dict(common_sha256=common_digest,answer_sha256=sh(state['answers'][arm].encode()),
                           source_sha256=seals[short],attempts=attempts,usage={k:sum(r['usage'][k] for r in raw) for k in ('prompt_tokens','completion_tokens','total_tokens')}))
                    print('frozen',short,'calls',len(raw),flush=True)
        freeze(OUT/'sealed-all.json',dict(design=content_hash(OUT/'design.json'),submissions=seals))
    print('All paired submissions sealed',len(seals),flush=True)
if __name__=='__main__':
    main()

