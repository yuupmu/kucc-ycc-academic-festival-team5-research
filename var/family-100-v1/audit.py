"""Offline, hash-checked reconstruction of reviewer -> owner -> writer -> executed snapshots."""
import collections
import hashlib
import json
from pathlib import Path
from itertools import combinations
from study import root, TASKS,MODELS,read, key, reply, PUBLIC
from backend.project_review import digest
from backend.structured_output import decode
from backend.allocation_repair import apply_edits
from experiments.scoped_transfer import bound_edits,evidence_choices
from experiments.transfer100_report import execute
from experiments.local_transport import save

bank=Path('experiments/transfer100-20261126')
filehash=lambda src:hashlib.sha256(src.encode()).hexdigest()
labels=read(root/'labels.json')
cache={}
def payload(d,k):
    raw=read(d/'calls'/(k+'.json'))
    assert digest([raw['role'],raw['request']])==k
    data=decode(raw['text'],raw['request']['response_format']['json_schema']['schema']) if raw['finish_reason']=='stop' else None
    return raw,json.loads(raw['request']['messages'][1]['content']),data

def marks(t,code,items):
    rows=execute(t,{'files':{'solution.py':code},'sha256':filehash(code)},items,cache)
    return {r['id']:dict(value=(x['actual'] or {}).get('value'),error=x['error'] or (x['actual'] or {}).get('exception'),
                          correct=not (x['error'] or (x['actual'] or {}).get('exception')) and
                          type((x['actual'] or {}).get('value')) is type(r['expected']) and (x['actual'] or {}).get('value')==r['expected'])
            for r,x in zip(items,rows)}

def coarse(t,codes):
    # Question topics, e.g. "hidden file", are distinct from evidence sufficient for a given input.
    table={'title':{'s':'spaces','e':'empty','h':'hyphen'},
           'suffix':{'m':'multi','c':'case','h':'hidden','x':'hidden','n':'missing','t':'missing'},
           'mask':{'d':'visible','k':'visible','s':'short','e':'empty'},
           'upload':{'l':'limit','b':'equal','z':'empty'},'print':{'w':'width','h':'height','b':'equal','z':'zero'}}
    return set(table[t][k] for k in codes if k in table[t])

def complete_topics(t,codes):
    requirements={'title':['s','h','e'],'suffix':['m','c','hx','nt'],'mask':['dk','s','e'],
                  'upload':['l','b','z'],'print':['w','h','b','z']}
    return sum(set(required)<=set(codes) for required in requirements[t])


def grounded(t,r,codes):
    basic={'spaces':'s','hyphen':'h','multi':'m','case':'c','limit':'l','equal':'b','short':'s',
           'width':'w','height':'h','zero':'z','visible':'dk','empty':'z' if t=='upload' else 'e'}
    needs=set()
    for name in r['required']:
        if name=='missing':needs.add('t' if r['args'][0].endswith('.') else 'n')
        elif name=='hidden':needs.add('x' if r['args'][0].count('.')>1 else 'h')
        else:needs.update(basic[name])
    if t=='print' and needs=={'w','h'} and r['skill']=='interaction' and r['args'][0]>6 and r['args'][1]>4:
        return bool({'w','h'}&codes)
    return needs<=codes

# Old replies were free text. This is manual coding of explicit answers, not the questions.
OLD_FIRST={'title':['sh','sh'],'suffix':['m','mchxnt'],'mask':['dkse','dks'],
           'upload':['lz','lbz'],'print':['whbz','whbz']}

def tally(seq):
    return dict(collections.Counter(seq))

def inspect(d,t,a,items,old):
    initial=(d/'submissions/solo/solution.py').read_text()
    final=(d/'submissions'/a/'solution.py').read_text()
    assert filehash(final)==read(d/'sealed.json')[a]
    declared=read(d/(a+'.json'))['calls']
    prior=read(d/'solo.json')['calls']; hist=[];pre=initial; log=[];known=set()
    def receipt(q):return set(labels[key(t,q)])
    if a!='solo':
        for n in (1,2,3):
            prefix=f'{a}-{n}';snap=read(d/(prefix+'-snapshot.json'))
            assert snap['calls'][:len(prior)]==prior
            extra=snap['calls'][len(prior):];prior=snap['calls']
            qs=read(d/(prefix+'-questions.json'))
            now=read(d/(prefix+'-reply.json')) if qs else None
            h=hist+([dict(request_id=prefix,questions=qs,answer={'text':now})] if qs else [])
            assert h==snap['dialogue']
            received=set().union(*(receipt(q) for q in qs))
            if not old and qs:assert reply(t,received)==now
            if old and n==1:known.update(OLD_FIRST[t][a=='abc'])
            elif not old:known.update(received)
            design=read(d/'design.json')
            reviewers={};issues=[];attempts=[];wanted=[];nextcode=pre;writer_calls=[]
            for k in extra:
                c,packet,doc=payload(d,k);role=c['role']
                assert packet['code']==pre
                if role!='main-edit':
                    schedule=design.get('reviewer_schedule')
                    wanted_model=schedule[n-1]['ABC'.index(role[-1])] if schedule and role.startswith('observer-') else design['model']
                    assert c['model']==wanted_model
                    assert packet['dialogue']==hist
                    if doc is not None:
                        ask=[q.strip() for q in doc['questions'] if q.strip()]
                        topics=set().union(*(receipt(q) for q in ask))
                        reviewers[role]=dict(model=c['model'],questions=ask,topics=sorted(coarse(t,topics)),
                                             issue=doc['issue'],key=k)
                        wanted.extend(ask)
                        if doc['issue'].strip():issues.append(doc['issue'])
                    elif role not in reviewers:
                        reviewers[role]=dict(model=c['model'],questions=[],topics=[],issue='',key=k)
                    continue
                assert c['model']==design['model']
                writer_calls.append(k)
                assert packet['dialogue']==h and packet['review']==issues and packet['evidence']==evidence_choices(h)
                if doc is None:
                    attempts.append(dict(key=k,status=c['finish_reason'] if c['finish_reason']!='stop' else 'invalid format'))
                    continue
                edits=bound_edits(doc,evidence_choices(h))
                try:
                    nextcode=apply_edits(pre,edits,h,[v['request_id'] for v in h])
                    attempts.append(dict(key=k,status='applied' if edits else 'empty',edit_count=len(edits)))
                except ValueError as error:
                    attempts.append(dict(key=k,status='rejected',reason=str(error)))
            assert list(dict.fromkeys(wanted))==qs
            assert nextcode==snap['code']
            scores=marks(t,nextcode,items)
            log.append(dict(round=n,reviewers=reviewers,delivered=qs,answer=now,
                            questions_topics=sorted(coarse(t,received)),known=sorted(known),
                            writer_calls=writer_calls,patch_attempts=attempts,changed=pre!=nextcode,
                            score=sum(v['correct'] for v in scores.values()),code_sha256=filehash(nextcode),
                            cumulative_tokens=sum(read(d/'calls'/(k+'.json'))['usage']['total_tokens'] for k in prior)))
            hist=h;pre=nextcode
    assert pre==final and prior==declared
    scores=marks(t,final,items)
    for r in items:
        scores[r['id']]['sufficient']=grounded(t,r,known)
    usage=dict(calls=len(declared),tokens=0)
    for k in declared:
        raw,_,_=payload(d,k)
        usage['tokens']+=raw['usage']['total_tokens']
    return dict(rounds=log,evidence=sorted(known),topics=sorted(coarse(t,known)),usage=usage,code_sha256=filehash(final),
                questions=sum(len(x['delivered']) for x in log),windows=sum(bool(x['delivered']) for x in log),
                writer_packets_checked=sum(len(x['writer_calls']) for x in log),cases=scores,
                correct=sum(v['correct'] for v in scores.values()),sufficient=sum(v['sufficient'] for v in scores.values()),
                grounded_correct=sum(bool(v['correct'] and v['sufficient']) for v in scores.values()))

def classify(t,r):
    topicsets=[set(x['topics']) for x in r['reviewers'].values()]
    assert len(topicsets)==3
    active=[s for s in topicsets if s]
    if len(active)<2:return 'zero_or_one_policy_asker'
    if len(active)==3 and all(s==active[0] for s in active):return 'three_same'
    if len(active)==2 and active[0]==active[1]:return 'two_same'
    if not any(a&b for a,b in combinations(active,2)):return 'distinct_no_overlap'
    return 'partly_overlapping'

def summarize(records):
    result={}
    for a,ts in records.items():
        summary={name:sum(x[name] for x in ts.values()) for name in ('correct','sufficient','grounded_correct','questions','windows','writer_packets_checked')}
        summary.update({k:sum(z['usage'][k] for z in ts.values()) for k in ['calls','tokens']})
        summary['topics']=sum(len(v['topics']) for v in ts.values())
        summary['complete_policy_cards']=sum(complete_topics(t,v['evidence']) for t,v in ts.items())
        summary['known_wrong']=summary['sufficient']-summary['grounded_correct']
        summary['missing_wrong']=100-summary['correct']-summary['known_wrong']
        summary['task_scores']={t:v['correct'] for t,v in ts.items()}
        summary['round_scores']=[sum(v['rounds'][i]['score'] for v in ts.values()) for i in range(3)] if any(v['rounds'] for v in ts.values()) else []
        summary['round_tokens']=[sum(v['rounds'][i]['cumulative_tokens'] for v in ts.values()) for i in range(3)] if summary['round_scores'] else []
        if a.endswith('abc') or a=='mixed':
            summary['same_or_complementary']=tally(classify(t,r) for t,v in ts.items() for r in v['rounds'])
            summary['first_round_overlap']={t:classify(t,x['rounds'][0]) for t,x in ts.items()}
            later=0; only={role:0 for role in ('observer-A','observer-B','observer-C')}
            for t,v in ts.items():
                previous=set()
                for r in v['rounds']:
                    topics=set(r['questions_topics'])
                    if r['round']>1:later+=len(topics-previous)
                    for role,rev in r['reviewers'].items():
                        peer=set().union(*(set(q['topics']) for k,q in r['reviewers'].items() if k!=role))
                        only[role]+=len(set(rev['topics'])-peer-previous)
                    previous|=topics
            summary['later_new_topics']=later;summary['unshared_new_topics_by_slot']=only
            reviewers=('observer-A','observer-B','observer-C')
            by_slots={}
            for n in (1,2,3):
                for slots in combinations(reviewers,n):
                    by_slots[''.join(k[-1] for k in slots)]=sum(len(set().union(*(
                        set(v['rounds'][0]['reviewers'][k]['topics']) for k in slots))) for v in ts.values())
            summary['first_round_question_topics_by_retained_slot']=by_slots
        result[a]=summary
    return result

def contrast(records,a,b):
    wins=[];losses=[]
    for t in TASKS:
        x,y=records[a][t]['cases'],records[b][t]['cases']
        assert set(x)==set(y)
        for k in x:
            if x[k]['correct']!=y[k]['correct']:
                (wins if y[k]['correct'] else losses).append(k)
    return dict(improved=wins,regressed=losses)

def audit(old):
    global labels
    labels=read(root/'labels.json')
    data=root.parent/'scoped-100-v1' if old else root/'runs'
    seals=read((data if old else root)/'sealed-all.json')
    allrows=read(bank/'evaluator/cases.json')
    out={}
    for group in (['A'] if old else ['A','B','C','mixed']):
        for t in TASKS:
            d=data/t if old else data/group/t
            seal=seals[t] if old else seals[group+'/'+t]
            for a in (['abc'] if group=='mixed' else ['solo','self','abc']):
                assert read(d/'sealed.json')[a]==seal[a]
                arm=group+'-'+a if group!='mixed' else group
                items=[r for r in allrows if r['task']==t];assert len(items)==20
                rec=inspect(d,t,a,items,old);out.setdefault(arm,{})[t]=rec
                if old:
                    official=read(d/'scores.json')[a]
                    assert rec['correct']==official['correct'] and rec['usage']['tokens']==official['tokens']
                    assert all(rec['cases'][x['id']]['correct']==x['correct'] for x in official['cases'])
    totals=summarize(out)
    pairs=[('A-self','A-abc')] if old else [(g+'-self',g+'-abc') for g in 'ABC']+[('A-abc','mixed'),('A-self','mixed')]
    comparisons={a+' -> '+b:contrast(out,a,b) for a,b in pairs}
    diag={}
    if old:
        # Direct test of the two real cycle-two proposals for mask, with only base indentation restored.
        d=data/'mask';items=[r for r in allrows if r['task']=='mask']
        for arm in ['self','abc']:
            snapshot=out['A-'+arm]['mask']['rounds'][1]
            k=snapshot['writer_calls'][0];c,packet,doc=payload(d,k)
            edits,=bound_edits(doc,evidence_choices(packet['dialogue']))
            source=packet['code'];start=source.index(edits['before']);end=start+len(edits['before'])
            indent=source[source.rfind('\n',0,start)+1:start]
            assert not indent.strip() and source.count(edits['before'])==1
            newafter=edits['after'].replace('\n','\n'+indent)
            code=source[:start]+newafter+source[end:]
            scores=marks('mask',code,items)
            try:
                apply_edits(source,[dict(edits,after=newafter)],packet['dialogue'],[h['request_id'] for h in packet['dialogue']])
                disposition='accepted'
            except ValueError as ex:disposition=str(ex)
            diag[arm]=dict(key=k,proposed=edits['after'],format_only_score=sum(x['correct'] for x in scores.values()),remaining_scope_check=disposition)
    result=dict(summary=totals,paired=comparisons,diagnostic_mask=diag,trace=out)
    save(root/('previous-process.json' if old else 'results.json'),result)
    if not old:
        save(root/'comparison.json',dict(summary=totals,paired=comparisons,model_paths=MODELS))
    for a,v in totals.items():print(a,{k:v.get(k) for k in ['correct','grounded_correct','tokens','topics','questions','windows','round_scores','same_or_complementary','first_round_overlap','later_new_topics','writer_packets_checked']})
    print('pairs',[(k,len(v['improved']),len(v['regressed'])) for k,v in comparisons.items()]);print('diag',diag)

if __name__=='__main__':
    import sys
    audit('--previous' in sys.argv)
