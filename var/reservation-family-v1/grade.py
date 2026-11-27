"""Score immutable submissions and trace decisions. Run only after study.py exits."""
import hashlib
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from study import OUT, REPO, OFFICIAL, SAMPLE, TASKS, GROUPS, MODELS, digest, question_key
from backend.allocation_repair import apply_edits
from backend.isolated import grade_isolated, run_cases
from backend.project_review import digest as request_digest
from backend.structured_output import decode
from experiments.local_transport import read, save
from experiments.pipeline100.grade import verdict
from experiments.rule_cycle_report import TRACE
from experiments.scoped_transfer import evidence_choices, bound_edits
from reservation_benchmark.score import load_cases

SEAL = read(OUT/'sealed-all.json')
assert set(SEAL) == {g+'/'+t for g in GROUPS for t in TASKS}
DESIGN = read(OUT/'design.json')
assert all(digest(REPO/path) == v for path,v in DESIGN['source_sha256'].items())
labels = read(OUT/'labels.json')
cards = read(OUT/'cards.json')
seconds = [x for x in read(SAMPLE) if x['task']=='reservation']
calendar, answers, version, policy_hash = load_cases()
assert len(seconds)==len({tuple(x['inputs']) for x in seconds})==50
assert len(calendar)==len({(x['now'],x['booked_at'],x['starts_at']) for x in calendar})==100


@lru_cache(None)
def assess(task, code):
    if task == 'reservation':
        raw = verdict(task,code,seconds)
        return {x['id']: {**raw[x['id']], 'category': x['type'], 'expected': x['expected']}
                for x in seconds}
    inputs = [dict(initial_state={'call':'can_cancel','args':[c[k] for k in ('now','booked_at','starts_at')]},
                   events=[]) for c in calendar]
    rows = {}
    for c,r in zip(calendar, run_cases(code+TRACE,inputs,'allocation',hash_seed=0)):
        value = r['actual'] or {}
        expected = answers[c['id']]['allowed']
        actual = value.get('value')
        error = r['error'] or value.get('exception')
        if error:
            status = '보류' if error=='NotImplementedError' else '실행 오류'
        elif type(actual) is not bool:
            status = '반환 형식 오류'
        else:
            status = '정답' if actual is expected else '오답'
        rows[c['id']] = dict(actual=actual,expected=expected,status=status,error=error,category=c['category'])
    return rows


@lru_cache(None)
def official(code):
    return grade_isolated(code,OFFICIAL)


@lru_cache(None)
def call(key):
    raw = read(OUT/'calls'/(key+'.json'))
    assert raw['model']==raw['request']['model']
    assert request_digest([raw['role'], raw['request']])==key
    usage = raw['usage']
    assert usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']
    packet = json.loads(raw['request']['messages'][1]['content'])
    response = decode(raw['text'],raw['request']['response_format']['json_schema']['schema']) if raw['finish_reason']=='stop' else None
    return raw,packet,response


def trace(group,task,arm):
    folder = OUT/'runs'/group/task
    design = read(folder/'design.json')
    project = read(OUT/'public'/(task+'.json'))
    code = (folder/'submissions/solo/solution.py').read_text()
    prior = read(folder/'solo.json')['calls']
    main = MODELS['A' if group=='mixed' else group]
    assert main == design['model'] and design['project'] == project
    for key in prior:
        raw,p,_ = call(key)
        assert raw['model']==main and raw['role']=='main' and p==project
    rounds, history = [], []
    for n in range(1, 4) if arm!='solo' else ():
        prefix = f'{arm}-{n}'
        snap = read(folder/(prefix+'-snapshot.json'))
        assert snap['calls'][:len(prior)]==prior
        extra = snap['calls'][len(prior):]
        prior = snap['calls']
        qs = read(folder/(prefix+'-questions.json'))
        codes = {c for q in qs for c in labels[question_key(task,q)]}
        answer = read(folder/(prefix+'-reply.json')) if qs else None
        if codes:
            assert answer == ' '.join(v for c,v in cards[task].items() if c in codes)
        elif qs:
            assert answer=='질문한 내용에 대해 더 정해진 답을 드리려면, 판단할 예약 상황이나 궁금한 운영 기준을 구체적으로 짚어 주세요.'
        current = history+([dict(request_id=prefix,questions=qs,answer={'text':answer})] if qs else [])
        assert current == snap['dialogue']
        proposed, issues, attempts, delivered = [], [], [], []
        updated = code
        for key in extra:
            raw,p,response = call(key)
            role = raw['role']
            assert p['code']==code and p['brief']==project['brief']
            if role != 'main-edit':
                assert set(p)=={'code','brief','dialogue'} and p['dialogue']==history
                selected = design['reviewer_schedule'][n-1]['ABC'.index(role[-1])] if role.startswith('observer-') else main
                assert raw['model']==selected
                if response:
                    qq = [q.strip() for q in response['questions'] if q.strip()]
                    delivered.extend(qq)
                    proposed.append({'role':role,'model':selected,'questions':qq,'topics':[labels[question_key(task,q)] for q in qq]})
                    if response['issue'].strip():
                        issues.append(response['issue'])
                continue
            assert raw['model']==main and p['dialogue']==current and p['review']==issues
            assert set(p) <= {'brief','code','dialogue','review','pending','evidence','edit_format_feedback'}
            assert p['evidence']==evidence_choices(current)
            if response is None:
                attempts.append({'status':'invalid','cause':raw['finish_reason']})
                continue
            changes = bound_edits(response,p['evidence'])
            try:
                updated = apply_edits(code,changes,current,[h['request_id'] for h in current])
                attempts.append({'status':'applied' if changes else 'empty','changes':len(changes)})
            except ValueError as exc:
                attempts.append({'status':'rejected','cause':str(exc)})
        assert list(dict.fromkeys(delivered))==qs and updated==snap['code']
        code, history = updated, current
        r = assess(task,code)
        rounds.append(dict(cycle=n,questions=qs,answer=answer,topics=sorted(codes),reviewers=proposed,edits=attempts,
                           score=sum(x['status']=='정답' for x in r.values()),
                           exact600=sum(x['status']=='정답' and x['category']=='정정 기간 끝점 600초' for x in r.values()) if task=='reservation' else None))
    path = folder/'submissions'/arm/'solution.py'
    assert code==path.read_text() and digest(path)==SEAL[group+'/'+task][arm]
    assert prior==read(folder/(arm+'.json'))['calls']
    rows = assess(task,code)
    topics = {t for r in rounds for t in r['topics']}
    substantiation = {}
    if task=='reservation':
        rows = {i: v.copy() for i,v in rows.items()}
        for item in seconds:
            requirements = item['owner_paths']
            rows[item['id']]['sufficient_evidence'] = not requirements or any(set(path)<=topics for path in requirements)
        substantiation = {
            'sufficient_evidence':sum(r['sufficient_evidence'] for r in rows.values()),
            'correct_with_sufficient_evidence':sum(r['sufficient_evidence'] and r['status']=='정답' for r in rows.values()),
        }
    if task=='calendar':
        ref = official(code)
        assert len(ref['results'])==len(rows)
        assert all(r['passed']==(rows[r['id']]['status']=='정답') and r['actual'] is rows[r['id']]['actual'] for r in ref['results'])
    usage = Counter()
    for key in prior:
        raw,packet,_ = call(key)
        usage.update({k:raw['usage'][k] for k in ('prompt_tokens','completion_tokens','total_tokens')})
        if raw['request']['max_tokens']==1800 or 'edit_format_feedback' in packet:
            usage['retry_calls']+=1
            usage['retry_tokens']+=raw['usage']['total_tokens']
    status = Counter(row['status'] for row in rows.values())
    score = status['정답']
    cat = {}
    for row in rows.values():
        bucket = cat.setdefault(row['category'], {'correct':0,'total':0})
        bucket['total']+=1
        bucket['correct']+=row['status']=='정답'
    return (dict(score=score,total=len(rows),status=dict(status),**dict(usage),calls=len(prior),
                 used_public_scaffold=(folder/'draft-fallback.json').exists(),
                 questions=sum(len(r['questions']) for r in rounds),topics=sorted(topics),
                 round_scores=[r['score'] for r in rounds],categories=cat,**substantiation),
            dict(rounds=rounds,code_sha256=digest(path),cases=rows))


def run():
    summary, details, paired = {}, {}, {}
    for task in TASKS:
        summary[task], details[task], paired[task] = {}, {}, {}
        for group in GROUPS:
            for arm in ('abc',) if group=='mixed' else ('solo','self','abc'):
                label = 'mixed' if group=='mixed' else group+'-'+arm
                brief, record = trace(group,task,arm)
                summary[task][label],details[task][label] = brief,record
                print(task,label,brief['score'],brief['status'],brief['total_tokens'],brief['round_scores'],flush=True)
        pairs = [(g+'-self', g+'-abc') for g in 'ABC']+[('A-self','mixed'),('A-abc','mixed')]
        for left,right in pairs:
            a,b=(details[task][label]['cases'] for label in (left,right))
            paired[task][left+' -> '+right]={
                'gained':[i for i in a if a[i]['status']!='정답' and b[i]['status']=='정답'],
                'lost':[i for i in a if a[i]['status']=='정답' and b[i]['status']!='정답'],
            }
    save(OUT/'details.json',details)
    save(OUT/'scores.json',{'models':MODELS,'seed':263,'cycles':3,'basic_composition':'50 old reservation-only items',
                            'calendar_version':version,'bank_policy_sha256':policy_hash,'results':summary,'paired':paired})


if __name__ == '__main__':
    run()
