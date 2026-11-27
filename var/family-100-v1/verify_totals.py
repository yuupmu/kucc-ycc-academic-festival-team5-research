from pathlib import Path
import hashlib,json
from collections import Counter
p=Path(__file__).resolve().parent
def read(q):return json.loads(q.read_text())
r=read(p/'results.json'); s=r['summary'];tr=r['trace']; assert len(s)==10
old=read(p/'previous-process.json')
for a,v in s.items():
    ids={k for row in tr[a].values() for k in row['cases']}; assert len(ids)==100
    refs=(p/'runs'/'mixed' if a=='mixed' else p/'runs'/a.split('-')[0])
    key='abc' if a=='mixed' else a.split('-')[1]
    seals=read(p/'sealed-all.json'); expected=Counter()
    for t,rec in tr[a].items():
        src=refs/t/'submissions'/key/'solution.py'
        assert hashlib.sha256(src.read_bytes()).hexdigest()==rec['code_sha256']==seals[refs.name+'/'+t][key]
        assert rec['correct']==sum(x['correct'] for x in rec['cases'].values())
        for k in read(refs/t/(key+'.json'))['calls']:
            call=read(p/'calls'/(k+'.json'));expected['tokens']+=call['usage']['total_tokens'];expected['calls']+=1
    assert v['correct']==sum(v['task_scores'].values()) and all(v[k]==expected[k] for k in expected)
    print(a,'pts',v['correct'],'grounded',v['grounded_correct'],'qtokens',v['tokens'],'questions/windows',v['questions'],v['windows'],'policies',v['complete_policy_cards'],'sufficient',v['sufficient'],'tasks',list(v['task_scores'].values()),'cycles',v['round_scores'])
    if v.get('same_or_complementary'):print('diversity',v['same_or_complementary'],v['first_round_question_topics_by_retained_slot'],'after round1 new',v['later_new_topics'])
for pair,rows in r['paired'].items():
    print(pair,'wins',len(rows['improved']),'losses',len(rows['regressed']),'diff',Counter(k.split('-')[0] for k in rows['improved']),Counter(k.split('-')[0] for k in rows['regressed']))
print('PREV',[(a,v['correct'],v['sufficient'],v['grounded_correct'],v['round_scores'],v['round_tokens']) for a,v in old['summary'].items()])
