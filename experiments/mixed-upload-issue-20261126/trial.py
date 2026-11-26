"""One paired revision; two downstream cycles only after a sealed, regression-free improvement."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
DELTA = OUT.parent/'family-reply-delta-20261126'
sys.path[:0] = [str(LAB),str(DELTA)]
import run as previous
import issue_editor
from backend.project_review import digest
from backend.structured_output import array, decode, obj
from experiments import guarded_reply, reply_pipeline, scoped_reply_writer, scoped_transfer_v2 as flow
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read, recorded
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING, VIEWS

HIST = previous.FAMILY/'runs/mixed/upload'
CONFIG = read(HIST/'design.json')
MODEL = CONFIG['model']
CASES = LAB/'experiments/transfer100-20261126/evaluator/cases.json'
sha = previous.sha


def setup():
    seen = read(HIST/'solo.json')['calls']
    snap = read(HIST/'abc-1-snapshot.json')
    questions, issues, old = [], [], []
    for key in snap['calls'][len(seen):]:
        raw=read(HIST/'calls'/(key+'.json'))
        assert digest([raw['role'],raw['request']]) == key
        if raw['role']=='main-edit':
            old.append(key)
        else:
            doc=decode(raw['text'],raw['request']['response_format']['json_schema']['schema'])
            assert raw['finish_reason']=='stop' and doc is not None
            questions.extend(q.strip() for q in doc['questions'] if q.strip())
            if doc['issue'].strip(): issues.append(doc['issue'])
    history=snap['dialogue']
    assert list(dict.fromkeys(questions))==history[0]['questions']==read(HIST/'abc-1-questions.json')
    assert history[0]['answer']['text']==read(HIST/'abc-1-reply.json')
    draft=(HIST/'submissions/solo/solution.py').read_text()
    p=previous.source_packet(CONFIG['project']['brief'],draft,history,issues)
    original=read(HIST/'calls'/(old[0]+'.json'))['request']
    assert json.loads(original['messages'][1]['content'])==p and len(issues)==2
    freeze(OUT/'input.json',p)
    boundary, empty='@pending:12:4','@pending:8:8'
    scope=dict(input_digest=digest(p),finding_review='Researcher coded scope before inference; no annotation is transmitted to a model.',
               findings=[dict(issue=issues[0],sites=[empty,boundary]),dict(issue=issues[1],sites=[boundary])],
               checked_evidence=[
                   dict(source='public',quote='음수 입력은 잘못된 크기이므로 거부합니다.'),
                   dict(source='public',quote='담당자가 정한 상한보다 작은 양수 파일은 허용하고 상한보다 큰 파일은 거부합니다.'),
                   dict(source='abc-1/H1',quote='상한은 16바이트입니다.'),
                   dict(source='abc-1/H1',quote='정확히 상한이면 허용합니다.'),
                   dict(source='abc-1/H1',quote='0바이트 빈 파일은 거부합니다.')])
    assert issue_editor.authorized(p,scope)
    freeze(OUT/'scope.json',scope)
    paths=[OUT/'input.json',OUT/'scope.json',Path(__file__),Path(issue_editor.__file__),OUT/'assess.py',
           DELTA/'run.py',DELTA/'new-labels.json',HIST/'design.json',HIST/'abc-1-snapshot.json',
           HIST/'abc-3-snapshot.json',HIST/'sealed.json',previous.FAMILY/'cards.json',previous.FAMILY/'labels.json',
           previous.FAMILY/'study.py',previous.FAMILY/'weights.json',CASES,
           LAB/'experiments/transfer100_report.py',LAB/'backend/allocation_repair.py',
           LAB/'experiments/festival_protocol.py',LAB/'experiments/local_transport.py',
           *[Path(m.__file__) for m in (flow,guarded_reply,reply_pipeline,scoped_reply_writer)],
           *[HIST/'calls'/(k+'.json') for k in snap['calls']]]
    freeze(OUT/'design.json',dict(model=MODEL,seed=original['seed'],weights=previous.WEIGHTS,
           original_round1_edit_calls=old, controls='Same archived public brief, draft, three questions, one owner reply, two issues, 273 seed, weights and normal editor limits. Each editor gets one fresh invocation; built-in formatting retries count.',
           variant='Matched scope + existing behavior reader and Boolean predicate editor. Pass original draft, pending sites and verbatim review to the predicate call.',
           gate='Seal both round-1 source files before grading on the official 20. Continue only when gained >= 1 and lost == 0. No scores or evaluator data in any model call. No alternative seed or candidate.',
           files={str(p.relative_to(LAB)):sha(p) for p in paths}))


def design():
    d=read(OUT/'design.json')
    for name,checksum in d['files'].items():
        if sha(LAB/name)!=checksum: raise ValueError('Frozen input changed: '+name)
    return d


class Wire:
    def __init__(self, stack, folder, replay=False, reuse=False):
        self.stack,self.folder,self.replay,self.reuse=stack,folder,replay,reuse
        self.ports,self.logs={},{}
        folder.mkdir(parents=True,exist_ok=True)

    def call(self, model, role, prompt, packet, schema, seed, limit):
        def infer(path,role,system,user,call_seed,cap,port,fmt,model):
            archive=HIST/'calls'/path.name
            location=archive if self.reuse and archive.is_file() else path
            if not location.exists():
                if self.replay: raise ValueError('Missing model record '+path.name)
                if model not in self.ports:
                    family=next(k for k,v in previous.MODELS.items() if v==model)
                    if sha(LAB/model)!=previous.WEIGHTS[family]['sha256']: raise ValueError('Model changed')
                    endpoint=18976+'ABC'.index(family)
                    self.stack.enter_context(local_server(endpoint,model))
                    self.ports[model]=endpoint
                recorded(location,role,system,user,call_seed,cap,self.ports[model],fmt,model)
            raw=read(location)
            self.logs[path.stem]=dict(path=str(location.relative_to(LAB)),sha256=sha(location),
                                      role=role,model=model,tokens=raw['usage']['total_tokens'])
            return raw
        return call_model(self.folder,{'model':model},role,prompt,packet,schema,seed,limit,0,invoke=infer)


def edit(p,seed,wire,method,scope):
    def ask(role,prompt,packet,fmt,call_seed,cap):
        return wire.call(MODEL,role,prompt,packet,fmt,call_seed,cap)
    admitted=issue_editor.authorized(p,scope)
    if method=='old' or not (admitted or guarded_reply.scalar_parameter(p)):
        code,calls=previous.direct(dict(p),seed,ask)
        return code,dict(method='direct',calls=calls)
    def raw(out,design,role,prompt,packet,schema,call_seed,cap,port):
        return ask(role,prompt,packet,schema,call_seed,cap)
    guarded=issue_editor.with_scope(raw,scope)
    def author(role,prompt,packet,schema,call_seed,cap):
        return guarded(wire.folder,{'model':MODEL},role,prompt,packet,schema,call_seed,cap,0)
    code, trace=scoped_reply_writer.revise(p['brief'],p['code'],p['dialogue'],p['review'],seed,author)
    return code,dict(method='reviewed pending scope' if admitted else 'retained guard',**trace)


def publish(folder,code,trace):
    folder.mkdir(exist_ok=True,parents=True)
    path=folder/'solution.py'
    if path.exists() and path.read_bytes()!=code.encode(): raise ValueError('Published source changed')
    if not path.exists(): path.write_bytes(code.encode())
    freeze(folder/'trace.json',trace)
    return dict(code=sha(path),trace=sha(folder/'trace.json'))


def paired(replay=False):
    d=design()
    state,scope=read(OUT/'input.json'),read(OUT/'scope.json')
    seals={}
    for name in ('old','new'):
        dest=OUT/'round-1'/name
        with ExitStack() as stack:
            wire=Wire(stack,dest,replay=replay)
            code,trace=edit(state,d['seed'],wire,name,scope)
        if name=='new':
            predicates=[rec for rec in wire.logs.values() if rec['role']=='main-predicates']
            if not predicates: raise ValueError('Trial did not reach the predicate editor')
            for rec in predicates:
                actual=json.loads(read(LAB/rec['path'])['request']['messages'][1]['content'])
                assert all(actual[k]==state[k] for k in issue_editor.FIELDS)
        seals[name]=publish(dest,code,dict(input_digest=digest(state),**trace,raw=wire.logs))
    freeze(OUT/'round-1-seal.json',dict(design=sha(OUT/'design.json'),submissions=seals))


def follow(replay=False):
    design()
    permit=read(OUT/'continuation.json')
    if permit!={'round1_seal':sha(OUT/'round-1-seal.json'),'continue':True}:
        raise ValueError('First-round continuation criterion not met')
    p=read(OUT/'input.json')
    scope=read(OUT/'scope.json')
    first=OUT/'round-1/new'
    assert sha(first/'solution.py')==read(OUT/'round-1-seal.json')['submissions']['new']['code']
    source=(first/'solution.py').read_text()
    history=p['dialogue'].copy()
    labels=read(DELTA/'new-labels.json').copy()
    if (OUT/'new-labels.json').exists(): labels.update(read(OUT/'new-labels.json'))
    seals={}
    with ExitStack() as stack:
        dest=OUT/'follow'
        wire=Wire(stack,dest,replay=replay,reuse=True)
        for n in (2,3):
            seed=CONFIG['seed']+10*n
            packet=dict(brief=p['brief'],code=source,dialogue=history)
            qs,issues,calls=[],[],[]
            for i,view in enumerate(VIEWS):
                reviewer=CONFIG['reviewer_schedule'][n-1][i]
                for cap in (1100,1800):
                    key,doc=wire.call(reviewer,'observer-'+'ABC'[i],'당신은 독립 감시자입니다. '+view+flow.REVIEW,
                                      packet,obj({'questions':array(STRING,0,1),'issue':STRING}),seed+i,cap)
                    calls.append(key)
                    if doc is not None:
                        qs.extend(q.strip() for q in doc['questions'] if q.strip())
                        if doc['issue'].strip(): issues.append(doc['issue'])
                        break
            qs=list(dict.fromkeys(qs))
            answer=None
            if qs:
                answer,_,unknown=previous.owner('transfer','upload',qs,labels)
                if unknown:
                    if replay: raise ValueError('Missing owner labels')
                    freeze(OUT/f'owner-window-{n}.json',unknown)
                    print(json.dumps(unknown,ensure_ascii=False),flush=True)
                    return
                history=history+[dict(request_id='abc-'+str(n),questions=qs,answer={'text':answer})]
            trace=dict(method='no-edit',calls=[])
            if qs or issues:
                packet=previous.source_packet(p['brief'],source,history,issues)
                source,trace=edit(packet,seed,wire,'new',scope)
            all_calls=calls+trace['calls']
            seals[str(n)]=publish(dest/str(n),source,dict(writer=trace,questions=qs,issues=issues,answer=answer,
                                  calls=all_calls,raw={k:wire.logs[k] for k in all_calls}))
    freeze(OUT/'final-seal.json',dict(round1=sha(OUT/'round-1-seal.json'),rounds=seals,owner_labels=digest(labels)))


if __name__=='__main__':
    os.chdir(LAB)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','pair','replay-pair','follow','replay-follow'))
    action=parser.parse_args().action
    with locked_output(OUT):
        if action=='prepare': setup()
        elif action in ('pair','replay-pair'): paired(replay=action.startswith('replay'))
        else: follow(replay=action.startswith('replay'))
