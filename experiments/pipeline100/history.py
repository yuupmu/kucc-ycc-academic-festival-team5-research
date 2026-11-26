"""Older model families on the common reservation subset, and the two-task transfer pilot."""
from pathlib import Path
from hashlib import sha256
from collections import Counter
from experiments import festival_mini as mini
from experiments.local_baseline import submission_text
from experiments.local_transport import read
from experiments.pipeline100.records import ARCH,rel

def analyze(sample,run):
    rows,dialogues,scope=[],[],[]
    def add(family,arm,seed,task,code,path,model,tokens=None,calls=None,cost_scope='독립 조건',window_count=0):
        judged=run(task,code)
        counts=Counter(v['status'] for v in judged.values())
        assert sum(counts.values())==50
        rows.append(dict(family=family,arm=arm,seed=seed,task=task,model=Path(model).name,
                         correct=counts['정답'],wrong=counts['오답'],defer=counts['보류'],errors=counts['실행 오류']+counts['반환 형식 오류'],
                         cost_scope=cost_scope,tokens=tokens,calls=calls,windows=window_count,source=rel(path),
                         sha=sha256(code.encode()).hexdigest(),items=judged))
    def record(family,arm,seed,task,n,q,answer,src,mode,by=''):
        dialogues.append(dict(family=family,arm=arm,seed=seed,task=task,cycle=n,by=by,question=q,answer=answer,source=rel(src),mode=mode))
    def log_scope(d,reason):
        scope.append(dict(folder=d,scope=reason))
    series=['qwen3-blind-abcd-20261126','qwen3-serial-revisions-20261126','qwen3-source-revisions-20261126','qwen3-public-clock-review-20261126']
    for fam in series:
        p=ARCH/fam
        for s in read(p/'submissions.json'):
            assert sha256(s['code'].encode()).hexdigest()==s['sha256']
            raw=[read(p/str(s['seed'])/k) for k in s['calls']]
            add(fam,s['arm'],s['seed'],'reservation',s['code'],p/'submissions.json',raw[0]['model'],
                sum(c['usage']['total_tokens'] for c in raw),len(raw))
        log_scope(fam,'예약 공통 50 · 사전 고정 제출 · 사람에게 질문하는 역할 없음')
    for p in sorted(ARCH.glob('qwen3-*')):
        if not (p/'state.json').is_file() or not (p/'round-001').is_dir():
            continue
        design=read(p/'design.json');state=read(p/'state.json')
        measured=read(p.with_name(p.name+'-research')/'summary.json')
        for role in ('self','multi'):
            version=state.get('arms',{}).get(role,{}).get('version') or state['version']
            path=p/f'round-{version:03}'/role/'snapshot.json'
            submitted=read(path);code=submitted['code']
            assert sha256(code.encode()).hexdigest()==submitted['sha256']
            responses=[a for a in state['answers'] if a.get('arm',role)==role]
            u=measured['usage'][role]
            add(p.name,role,design['seed'],'reservation',code,path,design['model'],u['tokens'],u['calls'],window_count=len(responses))
            for a in responses:
                for q in a['questions']:
                    mapping=a.get('sources_by_question',{}).get(q,[])
                    full=a.get('scoped_replies',{})
                    if mapping and all(k in full for k in mapping):
                        text='\n'.join(full[k] for k in mapping);mode='질문별 기록'
                    else:
                        text=a['text'];mode='당시 회신 묶음 전체 · 개별 귀속 미확인'
                    record(p.name,role,design['seed'],'reservation',a['batch'],q,text,p/'state.json',mode)
        log_scope(p.name,'예약 공통 50 · 당시 최종 회차 · 미해결 종료 포함')
    p=ARCH/'qwen3-review-cycles-20261125'
    for folder in sorted(x for x in p.iterdir() if x.is_dir() and x.name.isdigit()):
        seed=int(folder.name)
        for n in (0,1,2,3):
            f=folder/f'{n}-main.json';d=read(f)
            calls=[x for x in folder.glob('*.json') if x.name.split('-')[0].isdigit() and int(x.name.split('-')[0])<=n
                   and 'usage' in read(x)]
            add(p.name,f'편집 후 {n}회차',seed,'reservation',submission_text(d['text']),f,d['model'],
                sum(read(x)['usage']['total_tokens'] for x in calls),len(calls))
    log_scope(p.name,'예약 공통 50 · 편집자 D와 메인 수정 · 0~3회차')
    p=ARCH/'qwen3-editor-replay-20261125'
    for s in read(p/'results.json'):
        f=p/str(s['seed'])/s['arm']/'main.json';d=read(f)
        add(p.name,s['arm'],s['seed'],'reservation',submission_text(d['text']),f,d['model'],
            s['usage']['total_tokens'],2,'편집자와 메인 구간만')
    log_scope(p.name,'예약 공통 50 · 두 스냅샷 편집자 변형 · 토큰은 변경 구간')
    p=ARCH/'abc-timed-run'
    for file in sorted(p.glob('*-A.json')):
        initial=read(file)
        shared=initial['calls']
        for arm in 'ABC':
            f=file.with_name(file.name[:-6]+arm+'.json');s=read(f)
            raw=shared if arm=='A' else shared+s['calls']
            seed=s['seed'];fam=p.name+'/'+s['series'];counter=0
            if initial.get('operator_answer'):
                counter+=1
                record(fam,arm,seed,'reservation',1,shared[0]['text'],initial['operator_answer'],file,'초안 전 실제 응답','main')
            if arm!='A' and s.get('operator_answer'):
                qs=[c['review']['question'] for c in s['calls'] if c.get('review',{}).get('question','').strip()]
                if qs:
                    counter+=1
                for q in qs:
                    record(fam,arm,seed,'reservation',2,q,s['operator_answer'],f,'검토 후 회신 묶음 전체 · 개별 귀속 미확인')
            add(fam,arm,seed,'reservation',s['submission'],f,raw[0]['model'],
                sum(c['usage']['total_tokens'] for c in raw),len(raw),window_count=counter)
    log_scope(p.name,'예약 공통 50 · 3모델의 초안 A/자체 B/독립 C · 초기 질문 허용')
    p=mini.FIXTURES
    for t in ('reservation','triage'):
        folder=p/'runs'/t;design=read(folder/'design.json');state=read(folder/'state.json')
        for arm,cfg in state['arms'].items():
            n=cfg['version']; file=folder/f'round-{n:03}'/arm/'snapshot.json';snap=read(file)
            raw=[read(x) for i in range(1,n+1) for x in (folder/f'round-{i:03}'/'calls').glob('*.json')
                 if x.name.startswith((arm+'-','shared-'))]
            answers=[a for a in state['answers'] if a['arm']==arm]
            add(p.name,arm,design['seed'],t,next(iter(snap['files'].values())),file,design['author_model'],
                sum(c['usage']['total_tokens'] for c in raw),len(raw),window_count=len(answers))
            from experiments.transfer_study import operator_reply,core
            cards=read(p/'operator-cards.json')[t]
            brief=design['project']['brief']
            vocab={**core.sources(brief,[]),**cards,'clarify':'어떤 경우의 처리를 물으시는지 조금 더 구체적으로 말씀해 주세요.','unset':'그 경우에 대한 별도의 운영 방침은 정해져 있지 않습니다.'}
            for a in answers:
                sel=p/'operator'/f"{t}-{arm}-{a['version']}.json";g=read(sel)
                assert g['questions']==a['questions'] and operator_reply(p,t,arm,a['version'],a['questions'],brief,cards)==a['text']
                for q,group in zip(a['questions'],g['selections']):
                    text='\n'.join(vocab[k] for k in group) if all(k in vocab for k in group) else a['text']
                    record(p.name,arm,design['seed'],t,a['version'],q['question'],text,sel,'당시 정책 선택 기록','·'.join(q['proposed_by']))
    log_scope(p.name,'두 프로젝트 각 50 · 예비 8B 모델 · 최종 코드의 실제 실행 오류 별도')
    for fam,why in [
        ('qwen3-verified-abcd-20261125','모델에 중간 실행 결과·기대값이 전달된 역사 실험'),
        ('qwen3-candidate-abcd-20261125','중간 실행 결과로 후보 선택·복구를 한 역사 실험'),
        ('abc-delivery-check','중간 실패값과 기대값을 전달한 전달경로 실험'),('abc-rebenchmark-20261125','중간 검사 실패에 따라 재수정한 실험'),
        ('qwen3-editor-opinions-20261125','코드 제출 없이 편집자 의견과 줄 예측만을 측정'),('full-information-single-20261125','처음부터 전체 정책을 제공'),
        ('pilot-qwen','모델·입력 변환 탐색. 대표 동일 조건 A·B·C는 abc-timed-run에서 평가'),
        ('festival-mini-20261126/refined','구두점 처리 시험판. 완성 P4와 P4 보류 버전을 본표에 포함'),
        ('rule-cycle-20261126/format-pilot','작성 양식 기술 점검. 완성 일반 코드·조건식·구간은 본표에 포함'),
        ('answer-fidelity-20261126/format-pilot','채점 전 제외한 해석 호출 예비안. 고정 회신 및 실운영 채점은 본표에 포함')]:
        log_scope(fam,why)
    return rows,dialogues,scope
