"""Replay an actual total budget using byte-identical recorded requests, without per-call quotas."""
from review_controls import BASE,read,freeze,content_hash
def main():
    confirmed=read(BASE/'results.json')
    limit=5050;out=[]
    for arm in confirmed['controls']:
        if arm['regime']!='same-calls':continue
        path=BASE/arm['condition'];sub=read(path/'submission.json')
        remaining=limit;spent=0;served=[];skipped=[];writer=True
        for role,row in [('review'+str(i+1),r) for i,r in enumerate(arm['questions'])]+[('writer',sub['record'])]:
            if not row:continue
            packet=read(path/'calls'/(row['call']+'.json'))
            prompt=packet['usage']['prompt_tokens'];requested=packet['request']['max_tokens']
            if remaining<=prompt:
                skipped.append(dict(role=role,remaining=remaining,minimum=prompt+1))
                if role=='writer':writer=False
                continue
            # All admitted calls keep their original maximum, seed, packet and sampling. A smaller cap would require an actual fresh call.
            if remaining<prompt+requested:raise RuntimeError('A new model call is required. Do not infer its outcome.')
            charged=packet['usage']['total_tokens'];remaining-=charged;spent+=charged
            served.append(dict(role=role,call=row['call'],tokens=charged))
        out.append(dict(condition=arm['condition'],served=served,skipped=skipped,tokens=spent,cap=limit,score=arm['score'] if writer else arm['draft'],
                     proposed=arm['proposed'],received=arm['selected'],implemented=arm['policy'] if writer else {}))
    freeze(BASE/'overall-cap.json',dict(origin=content_hash(BASE/'results.json'),cap=limit,policy='first come, shared pool, no per-step allocation; replay only exact admitted requests',rows=out))
    print([(r['condition'],r['tokens'],r['score'],[x['role'] for x in r['skipped']]) for r in out])
if __name__=='__main__':main()

