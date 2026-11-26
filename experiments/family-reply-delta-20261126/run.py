"""Replay the two ten-condition studies, invalidating only changed model requests."""
import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
LAB = OUT.parents[1]
sys.path.insert(0, str(LAB))
from backend.allocation_repair import apply_edits, pending_sites
from backend.project_review import digest
from backend.structured_output import array, decode, obj
from experiments import guarded_reply, reply_pipeline, scoped_reply_writer, scoped_transfer_v2 as flow
from experiments.festival_protocol import call_model
from experiments.local_transport import local_server, locked_output, read, recorded, save
from experiments.project_review import freeze
from experiments.scoped_transfer import STRING, VIEWS, bound_edits, edit_schema, evidence_choices

FAMILY = LAB/'var/family-100-v1'
RES = LAB/'var/reservation-family-v1'
PILOT = LAB/'experiments/scoped-behavior-20261126/retained'
BANKS = {'transfer':FAMILY, 'booking':RES}
WEIGHTS = read(FAMILY/'weights.json')
MODELS = {k:'var/local-models/'+v['filename'] for k,v in WEIGHTS.items()}
TRANSFER_TASKS = tuple(read(FAMILY/'design.json')['tasks'])
BOOKING_TASKS = tuple(read(RES/'design.json')['tasks'])
LABELS = [f'{g}-{a}' for g in 'ABC' for a in ('solo','self','abc')] + ['mixed']
spec = importlib.util.spec_from_file_location('frozen_transfer_study', FAMILY/'study.py')
family = importlib.util.module_from_spec(spec)
spec.loader.exec_module(family)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''):
            h.update(block)
    return h.hexdigest()


def rel(path):
    return str(path.relative_to(LAB))


def identities():
    for suite,tasks in [('transfer',TRANSFER_TASKS),('booking',BOOKING_TASKS)]:
        for task in tasks:
            for label in LABELS:
                group,arm = ('mixed','abc') if label=='mixed' else label.split('-')
                yield suite, task, label, arm, BANKS[suite]/'runs'/group/task


def setup():
    paths = [Path(__file__),OUT/'score.py',PILOT/'sealed.json',FAMILY/'weights.json',
             LAB/'experiments/transfer100-20261126/evaluator/cases.json',LAB/'experiments/pipeline100/sample.json',
             LAB/'reservation_benchmark/evaluator/cases.json',LAB/'reservation_benchmark/evaluator/answer_key.json',
             FAMILY/'audit.py', LAB/'experiments/transfer100_report.py',LAB/'backend/allocation_repair.py',
             LAB/'backend/isolated.py',LAB/'experiments/scoped_transfer.py',LAB/'experiments/local_transport.py',
             LAB/'experiments/festival_protocol.py',LAB/'reservation_benchmark/score.py',LAB/'reservation_benchmark/evaluator/policy.json',
             *[Path(m.__file__) for m in (reply_pipeline,guarded_reply,scoped_reply_writer,flow)]]
    for bank in BANKS.values():
        paths.extend(bank/name for name in ('design.json','cards.json','labels.json','sealed-all.json','study.py'))
    paths.extend([FAMILY/'results.json', RES/'scores.json', RES/'details.json'])
    freeze(OUT/'design.json',dict(conditions=LABELS, tasks={'transfer':list(TRANSFER_TASKS),'booking':list(BOOKING_TASKS)},
           seed=263, cycles=3, owner='Archived question-to-card labels; Codex codes new questions against the same cards before grading.',
           reuse='Unchanged drafts, reviews, direct edits and scores retain their verified archives. Skip unused reader on direct edits. Cache only exact model requests. Grade after sealing all 70.',
           weights=WEIGHTS,files={rel(p):sha(p) for p in paths}))


def source_packet(brief,code,history,issues):
    return dict(brief=brief,code=code,dialogue=history,review=issues,pending=pending_sites(code),evidence=evidence_choices(history))


def archived(suite, task, label, arm, folder):
    """Prove eligibility at every historical review window, without assessment data."""
    base = BANKS[suite]
    project = read(folder/'design.json')['project']
    source = (folder/'submissions/solo/solution.py').read_text()
    prior = read(folder/'solo.json')['calls']
    history, eligible, windows = [], [], []
    for n in range(1,4) if arm!='solo' else ():
        tag = f'{arm}-{n}'
        snap = read(folder/(tag+'-snapshot.json'))
        assert snap['calls'][:len(prior)]==prior
        issues, asked, edits = [], [], []
        for key in snap['calls'][len(prior):]:
            raw = read(base/'calls'/(key+'.json'))
            assert key==digest([raw['role'],raw['request']])
            body = json.loads(raw['request']['messages'][1]['content'])
            assert body['code']==source and body['brief']==project['brief']
            if raw['role']=='main-edit':
                edits.append(body)
            else:
                assert body['dialogue']==history
                doc = decode(raw['text'],raw['request']['response_format']['json_schema']['schema']) if raw['finish_reason']=='stop' else None
                if doc:
                    asked.extend(q.strip() for q in doc['questions'] if q.strip())
                    if doc['issue'].strip(): issues.append(doc['issue'])
        qs=list(dict.fromkeys(asked))
        assert qs==read(folder/(tag+'-questions.json'))
        if qs:
            history=history+[dict(request_id=tag,questions=qs,answer={'text':read(folder/(tag+'-reply.json'))})]
        assert history==snap['dialogue'] and bool(edits)==bool(history and (qs or issues))
        vacancy = False
        if edits:
            packet=source_packet(project['brief'],source,history,issues)
            assert edits[0]==packet
            vacancy = guarded_reply.scalar_parameter(packet) is not None
            if vacancy: eligible.append(n)
        windows.append(dict(cycle=n,edited=bool(edits),eligible=vacancy,questions=len(qs)))
        source,prior=snap['code'],snap['calls']
    path=folder/'submissions'/arm/'solution.py'
    group=folder.parent.name
    assert source==path.read_text() and prior==read(folder/(arm+'.json'))['calls']
    assert sha(path)==read(base/'sealed-all.json')[group+'/'+task][arm]==read(folder/'sealed.json')[arm]
    return dict(path=rel(path),sha256=sha(path),calls=prior,eligible=eligible,windows=windows)


class Requests:
    def __init__(self, stack, replay):
        self.stack, self.replay, self.opened, self.used = stack, replay, {}, {}
        self.pilot = {}
        for label,seal in read(PILOT/'sealed.json')['outputs'].items():
            dest=PILOT/'runs'/label
            if sha(dest/'writer.json')!=seal['trace']: raise ValueError('Pilot trace changed')
            for key,checksum in read(dest/'writer.json')['logs'].items():
                self.pilot[key]=(dest/'calls'/(key+'.json'),checksum)

    def call(self, bank, model, role, prompt, packet, schema, seed, limit):
        def infer(path, role, system, user, seed, limit, port, fmt, model):
            key=path.stem
            original=bank/'calls'/path.name
            if original.is_file():
                location, origin = original,'baseline'
            elif key in self.pilot:
                location, checksum = self.pilot[key]
                if sha(location)!=checksum: raise ValueError('Cached pilot call changed')
                origin='pilot'
            else:
                location,origin=path,'new'
                if not path.is_file():
                    if self.replay: raise ValueError('Replay missing call '+key)
                    if model not in self.opened:
                        which=next(g for g,m in MODELS.items() if m==model)
                        if sha(LAB/model)!=WEIGHTS[which]['sha256']: raise ValueError('Different local model')
                        endpoint=18970+'ABC'.index(which)
                        self.stack.enter_context(local_server(endpoint,model))
                        self.opened[model]=endpoint
                    recorded(path,role,system,user,seed,limit,self.opened[model],fmt,model)
            raw=read(location)
            self.used[key]=dict(path=rel(location),sha256=sha(location),origin=origin,role=role,tokens=raw['usage']['total_tokens'])
            return raw
        return call_model(OUT,{'model':model},role,prompt,packet,schema,seed,limit,0,invoke=infer)


def direct(packet,seed,ask):
    # The retained writer discards its behavior memo on this path. Use its exact outgoing request.
    choices=packet['evidence']
    schema=obj({'edits':array(edit_schema(choices),0,6)})
    calls=[]
    for retry in range(2):
        response=None
        for limit in (1100,1800):
            k,response=ask('main-edit',guarded_reply.DIRECT,packet,schema,seed+retry,limit)
            calls.append(k)
            if response is not None: break
        if response is None: break
        try:
            history=packet['dialogue']
            return apply_edits(packet['code'],bound_edits(response,choices),history,[e['request_id'] for e in history]),calls
        except ValueError as exc:
            packet['edit_format_feedback']=str(exc)
    return packet['code'],calls


def owner(suite,task,questions,extra):
    labels=read(BANKS[suite]/'labels.json')
    labels.update(extra)
    pairs=[(family.key(task,q),q) for q in questions]
    unknown={k:dict(suite=suite,task=task,question=q) for k,q in pairs if k not in labels}
    if unknown: return None,[],unknown
    codes={c for k,_ in pairs for c in labels[k]}
    cards=read(BANKS[suite]/'cards.json')[task]
    assert codes<=cards.keys()
    if suite=='transfer':
        assert cards==family.CARDS[task]
        text=family.reply(task,codes)
    else:
        text=' '.join(v for k,v in cards.items() if k in codes) or '질문한 내용에 대해 더 정해진 답을 드리려면, 판단할 예약 상황이나 궁금한 운영 기준을 구체적으로 짚어 주세요.'
    return text,sorted(codes),{}


def updated(suite,task,label,arm,folder,requests,extra):
    cfg=read(folder/'design.json')
    brief,model=cfg['project']['brief'],cfg['model']
    before=(folder/'submissions/solo/solution.py').read_text()
    calls=read(folder/'solo.json')['calls'].copy()
    history,rounds=[],[]
    for n in range(1,4):
        seed=cfg['seed']+n*10
        tag=f'{arm}-{n}'
        packet=dict(brief=brief,code=before,dialogue=history)
        qs,issues,round_calls=[],[],[]
        for i,view in enumerate(('전체 정책, 경계, 상호작용',) if arm=='self' else VIEWS):
            own=arm=='self'
            selected=model if own else cfg['reviewer_schedule'][n-1][i]
            role='main-review' if own else 'observer-'+'ABC'[i]
            prompt=('당신은 작성자입니다.' if own else '당신은 독립 감시자입니다.')+' '+view+flow.REVIEW
            schema=obj({'questions':array(STRING,0,3 if own else 1),'issue':STRING})
            for limit in (1100,1800):
                k,review=requests.call(BANKS[suite],selected,role,prompt,packet,schema,seed+i,limit)
                round_calls.append(k)
                if review is not None:
                    qs.extend(q.strip() for q in review['questions'] if q.strip())
                    if review['issue'].strip(): issues.append(review['issue'])
                    break
        qs=list(dict.fromkeys(qs))
        answer,topics=None,[]
        if qs:
            answer,topics,unknown=owner(suite,task,qs,extra)
            if unknown: return None,unknown
            history=history+[dict(request_id=tag,questions=qs,answer={'text':answer})]
        after=before
        mode='no-edit'
        if history and (qs or issues):
            packet=source_packet(brief,before,history,issues)
            def ask(role,prompt,body,schema,seed,limit):
                return requests.call(BANKS[suite],model,role,prompt,body,schema,seed,limit)
            if guarded_reply.scalar_parameter(packet) is not None:
                def transport(out,design,role,prompt,body,schema,seed,limit,port):
                    return ask(role,prompt,body,schema,seed,limit)
                retained=reply_pipeline.with_guards(transport)
                def author(role,prompt,body,schema,seed,limit):
                    return retained(OUT,{'model':model},role,prompt,body,schema,seed,limit,0)
                after,rec=scoped_reply_writer.revise(brief,before,history,issues,seed,author)
                edit_calls,mode=rec['calls'],'guard'
            else:
                after,edit_calls=direct(packet,seed,ask)
                mode='direct'
            round_calls.extend(edit_calls)
        calls.extend(round_calls)
        rounds.append(dict(cycle=n,mode=mode,questions=qs,answer=answer,topics=topics,issues=issues,
                           calls=round_calls,code=after,same_old_snapshot=(after==read(folder/(tag+'-snapshot.json'))['code'])))
        before=after
    dest=OUT/'runs'/suite/label/task
    dest.mkdir(parents=True,exist_ok=True)
    file=dest/'solution.py'
    if file.is_file():
        if file.read_bytes()!=before.encode(): raise ValueError('Frozen code changed')
    else: file.write_bytes(before.encode())
    freeze(dest/'rounds.json',rounds)
    return dict(path=rel(file),sha256=sha(file),calls=calls,rounds=rel(dest/'rounds.json'),rounds_sha256=sha(dest/'rounds.json')),{}


def run(replay=False):
    os.chdir(LAB)
    design=read(OUT/'design.json')
    for path,signature in design['files'].items():
        if sha(LAB/path)!=signature: raise ValueError('Design input changed: '+path)
    extra=read(OUT/'new-labels.json') if (OUT/'new-labels.json').exists() else {}
    scan,submissions,unknown={},{},{}
    with ExitStack() as stack:
        requests=Requests(stack,replay)
        for suite,task,label,arm,folder in identities():
            key='/'.join((suite,task,label))
            old=archived(suite,task,label,arm,folder)
            scan[key]=dict(windows=old['windows'],eligible=old['eligible'])
            record={k:old[k] for k in ('path','sha256','calls')}
            if old['eligible']:
                record,missing=updated(suite,task,label,arm,folder,requests,extra)
                unknown.update(missing)
                if record is None: continue
            submissions[key]=record
        freeze(OUT/'scan.json',scan)
        if unknown:
            if replay: raise ValueError('Missing owner receipt')
            save(OUT/'pending.json',unknown)
            print('Awaiting question labels:',json.dumps(unknown,ensure_ascii=False),flush=True)
            return
        if len(submissions)!=70: raise ValueError('Require all 70 submissions')
        freeze(OUT/'requests.json',requests.used)
    freeze(OUT/'sealed.json',dict(design=sha(OUT/'design.json'),scan=sha(OUT/'scan.json'),requests=sha(OUT/'requests.json'),
                                 new_labels=digest(extra),submissions=submissions))
    print('Sealed',len(submissions),'project-condition submissions;',Counter(v['origin'] for v in requests.used.values()),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('prepare','run','replay'))
    opts=p.parse_args()
    with locked_output(OUT):
        setup() if opts.action=='prepare' else run(opts.action=='replay')
