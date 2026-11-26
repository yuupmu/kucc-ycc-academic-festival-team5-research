"""Score question controls and the common-budget reviewer submissions after sealing."""
from collections import Counter
from pathlib import Path
from review_controls import OUT,LAB,BASE,BANK,variant_specs,argument,owner_cards,read,freeze,sh,content_hash
from score_pairs import correct,evaluate
GROUPS={'upload':{'l':list(range(6,13))+list(range(14,21)),'b':[13],'z':[5]},
        'print':{'w':[15,19],'h':[16,18,20],'b':[10,11,12,13,14],'z':[4,5,6]}}
NEEDS={'upload':{'l':{'l'},'b':{'l','b'},'z':{'z'}},'print':{'w':{'w'},'h':{'h'},'b':{'w','h','b'},'z':{'z'}}}
def main():
    seals=read(BASE/'sealed-all.json');design=read(BASE/'design.json')
    assert design['source']==content_hash(OUT/'review_controls.py')
    assert seals['labels']==content_hash(BASE/'owner-labels.json') and seals['questions']==content_hash(BASE/'sealed-questions.json')
    for key,val in seals['solutions'].items():assert content_hash(BASE/key/'solution.py')==val
    questions=read(BASE/'blind-questions.json');labels=read(BASE/'owner-labels.json')
    bank=read(BANK/'evaluator/cases.json')
    rows=[];quiz=[];cache={}
    for key,spec in variant_specs():
        folder=BASE/key;task=spec['task']
        review=read(folder/'review.json')
        proposed=list(dict.fromkeys(c for r in review if r['question'] for c in labels[sh((task+'\n'+r['question']).encode())[:16]]))
        public,draft=argument(spec)
        if spec['arm']=='main':
            target={'upload':'b','print':'z'}[task]
            asked=bool(review[0]['question'])
            is_complete=spec['doc']=='full'
            valid=review[0]['decoded']
            quiz.append(dict(condition=key,task=task,doc=spec['doc'],seed=spec['seed'],asked=asked,valid=valid,requested=proposed,
                             responsive=valid and (not asked if is_complete else target in proposed),
                             outside_missing=any(c!=target for c in proposed) if not is_complete else asked,
                             raw=review[0],tokens=review[0]['tokens']))
            continue
        receipt=read(folder/'submission.json')
        assert receipt['proposed']==proposed
        cases=[r for r in bank if r['task']==task]
        def get(code):
            k=(task,sh(code.encode()))
            if k not in cache:cache[k]=evaluate(code,cases[0]['function'],[r['args'] for r in cases])
            return [correct(a,r['expected']) for a,r in zip(cache[k],cases)]
        base=get(draft); final=get((folder/'solution.py').read_text())
        policy={}
        for c in receipt['selected']:
            ids=GROUPS[task].get(c)
            if not ids or not NEEDS[task][c].issubset(receipt['selected']):continue
            policy[c]=dict(before=all(base[i-1] for i in ids),after=all(final[i-1] for i in ids),n=len(ids))
        rows.append(dict(condition=key,**spec,proposed=proposed,selected=receipt['selected'],questions=review,
                         policy=policy,score=sum(final),draft=sum(base),
                         fixed=sum(v and not b for v,b in zip(final,base)),lost=sum(b and not v for v,b in zip(final,base)),
                         tokens=receipt['tokens'],review_tokens=sum(r['tokens'] for r in review),new_topics=len(set(proposed)&set(GROUPS[task])),
                         outcome=receipt['outcome']))
    freeze(BASE/'results.json',dict(controls=rows,quiz=quiz,rules=GROUPS))
    for x in rows:print(x['condition'],x['proposed'],x['selected'],x['score'],x['tokens'])
    print('full/partial correct',[(s,sum(q['responsive'] for q in quiz if q['doc']==s)) for s in ('full','missing')])
if __name__=='__main__':main()

