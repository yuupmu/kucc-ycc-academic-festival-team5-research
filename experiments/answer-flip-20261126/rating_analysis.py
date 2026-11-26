"""Compare sealed independent ratings, including quoted evidence, distinct from human reliability."""
import json
import re
from collections import Counter
from pathlib import Path
import sys
from proxy_ratings import DIR,OUT,LAB
from experiments.local_transport import read
from experiments.project_review import freeze
from run_pairs import content_hash

def norm(v):return ''.join(str(v).split())
def can(s):
    try:return True,json.loads(s)
    except (TypeError,ValueError):return False,None
def typed(a,b):return type(a) is type(b) and a==b
def digest_ratings(humans=False,typed_form=False):
    blind=read(OUT/'blind/inputs.json');labels=read(OUT/'evaluator/rating-key.json')
    rr={}
    usage={}
    source_dir=OUT/'proxy-typed' if typed_form else DIR
    if not humans:
        seals=read(source_dir/'sealed.json')
        assert len(seals['responses'])==24 and seals['design']==content_hash(source_dir/'design.json')
        for k,v in seals['responses'].items():assert content_hash(source_dir/k/'rating.json')==v
    for r in 'AB':
        order=read(OUT/'evaluator'/f'order-{r}.json')
        resp={};cost=0
        human=None
        if humans:
            human=read(OUT/'blind'/f'rating-{r}.json')
            assert human['reviewer']==r and {x['slot'] for x in human['responses']}==set(range(1,len(order)+1))
        for slot,i in enumerate(order,1):
            if humans:
                a=next(x for x in human['responses'] if x['slot']==slot)
                val=dict(decision=a['decision'],value_json=json.dumps(a['value'],ensure_ascii=False),quote=a['quote'],
                         reason=a['reason'],scope={'yes':'over','no':'within','uncertain':'unclear'}[a['excess']],excess_quote=a['reason'])
            else:
                dest=source_dir/r/f'{slot:02}';raw=read(dest/'rating.json');val=raw['response']
                if val is not None and typed_form:
                    choice=val['decision']
                    val={**val,'decision':choice['status'],'value_json':json.dumps(choice.get('result'),ensure_ascii=False)}
                cost+=sum(read(dest/'calls'/(k+'.json'))['usage']['total_tokens'] for k in raw['calls'])
            if val is None:
                resp[i]={'decision':'invalid','value':None,'scope':'invalid','quote_verified':False,'value_ok':False,'excess_quote_verified':False}
                continue
            source=blind[i]
            owners=[text for _,text in source['dialogue'] if text]
            texts=[source['brief'],*owners]
            def genuine(quote,bank):
                fragment=norm(quote).strip('“”"‘’')
                return len(fragment)>=3 and any(fragment in norm(t) for t in bank)
            good,value=can(val['value_json'])
            resp[i]=dict(**val,value=value,value_ok=good,quote_verified=genuine(val['quote'],texts),
                         excess_quote_verified=genuine(val['excess_quote'],owners))
        rr[r]=resp;usage[r]=cost
    summary=Counter();rows=[];margins={r:Counter() for r in 'AB'}; comparisons=Counter()
    for i,key in enumerate(labels):
        vals={r:rr[r][i] for r in 'AB'}
        a,b=vals.values()
        for r,x in vals.items():
            margins[r][x['decision']]+=1
            summary[r+'_known']+=int(x['decision']=='known')
            summary[r+'_quote_match']+=int(x['quote_verified'])
            summary[r+'_vs_old_label']+=int((x['decision']=='known')==key['sufficient'] and x['decision']!='invalid')
            if x['decision']=='known':
                summary[r+'_value_correct_given_known']+=int(x['value_ok'] and typed(x['value'],key['expected']))
            if x['scope']=='over':
                summary[r+'_flagged_extra']+=1;summary[r+'_flag_extra_quote_match']+=int(x['excess_quote_verified'])
        valid=all(x['decision'] in ('known','unknown') for x in vals.values())
        same=valid and a['decision']==b['decision']
        exact=same and (a['decision']=='unknown' or (a['value_ok'] and b['value_ok'] and typed(a['value'],b['value'])))
        scope_same=a['scope']==b['scope'] and a['scope']!='invalid'
        summary['binary_agree']+=int(same);summary['exact_agree']+=int(exact);summary['scope_agree']+=int(scope_same)
        summary['valid_pair']+=int(valid)
        comparisons[a['decision']+'/'+b['decision']]+=1
        rows.append(dict(item=i+1,key=key,ratings=vals,binary_agree=same,exact_agree=exact))
    n=len(labels);observed=summary['binary_agree']/n
    pe=sum(margins['A'][t]*margins['B'][t] for t in ('known','unknown'))/(n*n)
    kappa=(observed-pe)/(1-pe) if pe<1 and summary['valid_pair']==n else None
    return dict(n=n,source='human' if humans else 'two independent local model proxies',tokens=usage,summary=dict(summary),binary_table=dict(comparisons),kappa=kappa,rows=rows)
if __name__=='__main__':
    human='--human' in sys.argv
    typed_form='--typed' in sys.argv
    data=digest_ratings(human,typed_form)
    freeze(OUT/'evaluator'/('human-agreement.json' if human else 'ai-typed-agreement.json' if typed_form else 'ai-agreement.json'),data)
    print(data['source'],data['summary'],'kappa',data['kappa'])

