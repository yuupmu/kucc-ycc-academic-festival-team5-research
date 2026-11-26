"""Execute only sealed programs, with independent policy references and owner-question checks."""
import ast
import itertools
import json
from collections import Counter
from trial import ARMS, ARCHIVE, BLOCKS, CASES, MISSING, OUT, design, digest, freeze, get_agenda, read, sha
from backend.isolated import run_cases
from experiments.rule_cycle_report import TRACE

DEFER = '보류'


def integer_witnesses(programs):
    points={0,16}
    for source in programs:
        fn=ast.parse(source).body[0]
        for n in ast.walk(fn):
            if isinstance(n,ast.stmt) and n is not fn:
                assert isinstance(n,(ast.If,ast.Return,ast.Raise))
                if isinstance(n,ast.Return):
                    assert isinstance(n.value,ast.Constant) and type(n.value.value) is bool
                elif isinstance(n,ast.Raise):
                    exc=n.exc.func if isinstance(n.exc,ast.Call) else n.exc
                    assert isinstance(exc,ast.Name) and exc.id=='NotImplementedError'
                elif isinstance(n,ast.If):
                    for e in ast.walk(n.test):
                        assert isinstance(e,(ast.Constant,ast.Name,ast.Load,ast.Compare,ast.BoolOp,ast.UnaryOp,
                                             ast.And,ast.Or,ast.Not,ast.Lt,ast.LtE,ast.Eq,ast.NotEq,ast.Gt,ast.GtE,ast.USub,ast.UAdd))
                        if isinstance(e,ast.Name):
                            assert e.id=='size_bytes'
                        if isinstance(e,ast.Constant) and type(e.value) is int:
                            points.add(e.value)
                        if isinstance(e,ast.UnaryOp) and isinstance(e.op,(ast.USub,ast.UAdd)):
                            points.add(ast.literal_eval(e))
    ordered=sorted(points)
    return sorted({*points, ordered[0]-1,ordered[-1]+1,*(a+1 for a,b in zip(ordered,ordered[1:]) if a+1<b)})


def run(source, function, inputs):
    jobs=[dict(initial_state=dict(call=function,args=list(x)),events=[]) for x in inputs]
    rows=run_cases(source+TRACE,jobs,'allocation',hash_seed=0)
    result={}
    for x,row in zip(inputs,rows):
        val=row['actual'] or {}
        error=row['error'] or val.get('exception')
        result[x]=DEFER if error=='NotImplementedError' else ('error: '+str(error) if error or type(val.get('value')) is not bool else val['value'])
    assert len(result)==len(inputs)
    return result


def collect():
    d=design()
    first,final,delivery=(read(OUT/f) for f in ('first-seal.json','final-seal.json','delivery.json'))
    assert final['first']==sha(OUT/'first-seal.json')==delivery['first'] and final['delivery']==sha(OUT/'delivery.json')
    assert first['agendas']==sha(OUT/'agenda-seal.json')
    programs,qs={},{}
    for block,topic in BLOCKS.items():
        agenda=get_agenda(topic)
        for phase in (*ARMS,'yes','no'):
            follow=phase in ('yes','no')
            if follow and block+'/'+phase not in final['forks']:
                continue
            folder=OUT/'runs'/block/(MISSING if follow else phase)/(phase if follow else 'initial')
            seal,state=read(folder/'seal.json'),read(folder/'state.json')
            assert seal['state']==digest(state) and seal['code']==sha(folder/'solution.py')
            if follow:
                record=final['forks'][block+'/'+phase]
                assert record['parent']==digest(read(folder.parent/'initial/state.json'))
                assert record['seal']==sha(folder/'seal.json') and record['questions']==sha(folder/'questions.json')
            else:
                assert first['submissions'][block+'/'+phase]==[sha(folder/'seal.json'),sha(folder/'questions.json')]
            q=read(folder/'questions.json')
            assert q==[agenda['slots'][k]['question'] for k in state['pending']]
            assert all(v['quote'] in state['history'][v['turn']-1]['reply'] for v in state['confirmed'].values())
            programs[block,phase]=state['code']
            qs[block,phase]=q
    costs={}
    for key,checksum in final['calls'].items():
        f=OUT/'calls'/(key+'.json')
        c=read(f)
        assert sha(f)==checksum and digest([c['role'],c['request']])==key
        if c['role'] not in ('main','observer-A','observer-B','observer-C'):
            assert c['request']['seed']==d['seed'] and c['model']==d['model']
        payload=json.loads(c['request']['messages'][1]['content'])
        if c['role']=='owner-statements':
            assert set(payload)=={'owner_reply'}
        if c['role']=='bind-owner-statement':
            assert set(payload)=={'statement','asked_items','kind','items_in_sent_ticket'}
        group=('transfer_draft_and_original_review' if c['role'] in ('main','observer-A','observer-B','observer-C')
               else 'reused_exact_request' if (ARCHIVE/'calls'/f.name).exists() and sha(ARCHIVE/'calls'/f.name)==checksum else
               'new_ledger_calls')
        acc=costs.setdefault(group,Counter())
        acc.update(calls=1,prompt=c['usage']['prompt_tokens'],completion=c['usage']['completion_tokens'],tokens=c['usage']['total_tokens'])
    return programs,qs,delivery,costs


def main():
    all_code,questions,delivery,costs=collect()
    cases=[r for r in read(CASES) if r['task']=='upload']
    assert len(cases)==20
    official=[(r['args'][0],) for r in cases]
    controls={*( (x,) for x in range(-2,34)),(-1000000,),(1000000,)}
    witnesses=integer_witnesses(src for (bl,_),src in all_code.items() if BLOCKS[bl]=='upload')
    flags=list(itertools.product((False,True),repeat=2))
    cache,blocks={},{}
    for block,topic in BLOCKS.items():
        is_upload=topic=='upload'
        inputs=sorted(controls|set(official)|{(x,) for x in witnesses}) if is_upload else flags
        task_cases=official if is_upload else flags
        target=(16,) if is_upload else (True,True)
        stages,outputs={},{}
        for stage in (*ARMS,'yes','no'):
            if (block,stage) not in all_code:
                continue
            code=all_code[block,stage]
            if (topic,code) not in cache:
                cache[topic,code]=run(code,'allow_upload' if is_upload else 'run_fan',inputs)
            out=cache[topic,code]
            policy=DEFER if stage==MISSING else stage in ('include','yes')
            def expected(x):
                if x==target:
                    return policy
                return 0<x[0]<16 if is_upload else x==(True,False)
            wrong=[x for x in inputs if out[x]!=expected(x)]
            info=dict(received_policy_correct=sum(x not in wrong for x in task_cases),n=len(task_cases),
                      all_supported_inputs=not wrong,wrong=wrong,questions=questions[block,stage],
                      behavior=[out[(v,)] for v in (15,16,17)] if is_upload else [out[x] for x in flags])
            if is_upload:
                info.update(controls38=sum(x not in wrong for x in controls),
                            original_inclusive_20=sum(out[(r['args'][0],)]==r['expected'] for r in cases))
            stages[stage]=info
            outputs[stage]=out
        def changed(a,b):
            return [x for x in inputs if outputs[a][x]!=outputs[b][x]]
        diffs={'direct_yes_vs_no':changed('include','exclude')}
        if 'yes' in outputs and 'no' in outputs:
            for stage,other in [('yes','include'),('no','exclude')]:
                diffs[MISSING+'_to_'+stage]=changed(MISSING,stage)
                diffs[stage+'_vs_direct']=changed(stage,other)
            diffs['fork_yes_vs_no']=changed('yes','no')
        success=(len(stages)==5 and all(v['all_supported_inputs'] for v in stages.values()) and
                 len(questions[block,MISSING])==1 and delivery['tickets'][block]['target_only'] and
                 not any(questions[block,s] for s in ('include','exclude','yes','no') if s in outputs) and
                 all(v==([] if label.endswith('_vs_direct') else [target]) for label,v in diffs.items()))
        blocks[block]=dict(success=success,stages=stages,differences=diffs)
    result=dict(final_seal=sha(OUT/'final-seal.json'),blocks=blocks,unique_call_costs=costs,
        upload_integer_class_witnesses=witnesses,fan_order=flags,
        baseline_actual_receipts=sha(ARCHIVE/'received-policy-results.json'))
    freeze(OUT/'results.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    main()
