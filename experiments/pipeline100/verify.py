"""Cross-check old overlaps, cost accounting, outcome transitions and model packet keys after scoring."""
import json
from collections import Counter
from experiments import festival_mini as mini, three_cycle_study as old, answer_fidelity_study as fix, rule_cycle_study as rule
from experiments.pipeline100.design import ROOT,TASKS
from experiments.pipeline100.records import LABEL
from experiments.local_transport import read
from experiments.project_review import freeze

def main():
    R=ROOT/'research';sample=read(ROOT/'sample.json')
    scores={s['arm']:s for s in read(R/'scores.json')}
    snaps=read(R/'snapshots.json');items=read(R/'items.json')
    assert len(sample)==100 and len(scores)==26
    latest={(r['task'],r['arm']):r for r in snaps if r['final']}
    assert len(latest)==52 and all(len({tuple(i['inputs']) for i in sample if i['task']==t})==50 for t in TASKS)
    for t in TASKS:
        for a in LABEL:
            r=latest[t,a];assert r['total_tokens']==r['prompt_tokens']+r['completion_tokens'] and sum(r['counts'].values())==50
    for s in scores.values():
        assert s['correct']==s['old20']+s['new80']==sum(s['types'].values())==s['reservation']+s['triage']
        assert s['correct']-scores['solo']['correct']==s['gained']-s['lost']
        assert sum(s['diagnosis'].values())==100
    rules=read(rule.STUDY/'research/observations.json')['tasks']
    early=read(mini.STUDY/'research/comparison.json')['tasks']
    comparisons=0
    for a in ['solo','self','p2','p3','p4','current','infer','apply','both','self-apply','apply-program','both-program','self-program','apply-regions','both-regions','self-regions']:
        src=early if a in ('solo','self','p2','p3','p4') else rules
        assert sum(src[t][a]['metrics']['correct'] for t in TASKS)==scores[a]['old20']
        assert sum(src[t][a]['metrics']['total_tokens'] for t in TASKS)==scores[a]['total_tokens']
        comparisons+=1
    for name,stud in [('old',old),('fixed',fix)]:
        earlier=read(stud.STUDY/'research/observations.json')['tasks']
        for a in ('self','multi'):
            for t in TASKS:
                src=earlier[t][a]['3']['metrics']
                expect=src['cumulative_total_tokens'] if name=='old' else src['cum_total_tokens']
                assert latest[t,name+'-'+a]['total_tokens']==expect
            comparisons+=1
    for v in read(R/'transitions.json'):
        assert not (set(v['gained'])&set(v['lost']))
        assert set(v['gained']+v['lost'])<=set(v['changed'])
    # Inspect user-message field names, including nested lists, without searching the model's own prose.
    bad={'test_cases','case_id','passing_tests','answer_key','expected_output','benchmark_score','grader','가채점','채점 결과','정답표'}
    def keys(v):
        if isinstance(v,dict):
            return set(v).union(*(keys(x) for x in v.values()))
        if isinstance(v,list):
            return set().union(*(keys(x) for x in v))
        return set()
    calls=list((ROOT/'runs').glob('**/calls/*.json'))
    for p in calls:
        raw=read(p)
        packet=json.loads(raw['request']['messages'][1]['content'])
        assert not keys(packet).intersection(bad)
    assert len(items)==3800 and sum(i['final'] for i in items)==2600
    summary=dict(unique_items=100,common_arms=26,final_verdicts=2600,all_round_verdicts=3800,
        matched_archival_costs_and_overlaps=comparisons,model_packets_checked=len(calls),
        historical_candidates=len(read(R/'historical.json')),questions_linked=len(read(R/'questions.json')),
        historical_questions=len(read(R/'historical-qa.json')),new_receipts=read(R/'new-cost.json'))
    freeze(R/'verification.json',summary)
    paths=[ROOT/'sample.json',ROOT/'protocol.json',ROOT/'sample-correction.json',ROOT/'submission-manifest.json',
           *sorted(R.glob('*.json')),*sorted(ROOT.glob('*.py'))]
    freeze(ROOT/'analysis-manifest.json',{str(p.relative_to(ROOT)):mini.checksum(p) for p in paths})
    print(summary)
if __name__=='__main__':
    main()
