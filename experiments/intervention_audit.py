"""Researcher-side replay of the information visible in each recorded local model call."""
import argparse
import json
from pathlib import Path

from experiments import human_intervention as common, intervention_operator as operator
from experiments import question_guide as guide, rule_edits as rules, scoped_intervention as workflow, source_thresholds
from experiments.blind_candidates import digest
from experiments.local_baseline import submission_text
from experiments.monitor_cycles import read


def verify(condition,path,what):
    if not condition:
        raise ValueError(f'{path}: {what}')


def call(path,packet,system,instruction,schema):
    record=read(path)
    messages=record['request']['messages']
    text,rest=messages[1]['content'].split('\n',1)
    verify(len(messages)==2 and messages[0]=={'role':'system','content':system}
           and messages[1]['role']=='user' and json.loads(text)==packet and rest==instruction,path,'모델 입력')
    verify(record['request']['response_format']['json_schema']['schema']==schema,path,'응답 양식')
    decoded=rules.decode(record['text'],schema)
    verify(decoded is not None,path,'모델 출력')
    return decoded


def audit(run):
    spec,state=read(run/'design.json'),read(run/'state.json')
    ordered=spec['protocol'] in workflow.TABLE_PROTOCOLS
    guided=ordered or spec['protocol']==workflow.GUIDED_PROTOCOL
    verify(guided or spec['protocol']==workflow.PROTOCOL,run,'방식별 답변 실험만 재생할 수 있음')
    paths=set()
    batches=0
    for arm in common.ARMS:
        previous=None
        for n in range(1,state['arms'][arm]['version']+1):
            folder=common.round_path(run,n)
            branch=folder/arm
            answers=[a for a in state['answers'] if a['arm']==arm and a['batch']<n]
            base={'공개 과제':spec['public_task'],'처음 제공된 정책':spec['initial_policy'],'담당자 자연어 답변':[a['text'] for a in answers]}
            packet=dict(base)
            if previous:
                packet.update(자신의_직전_계획=previous['plan'],자신의_직전_코드=previous['code'])
            instruction=workflow.WRITE+'\n'+workflow.REVISION_FOCUS[min(n-1,2)]
            schema=workflow.AUTHOR
            texts=[spec['initial_policy'],*[a['text'] for a in answers]]
            statements=guide.citable_sentences(texts) if 'operator_scope' in spec else guide.sentences(texts)
            if guided and n>1:
                packet['담당자 원문 인용 번호']={str(i):s for i,s in enumerate(statements,1)}
                instruction=guide.TABLE_INSTRUCTION if ordered else guide.WRITE_INSTRUCTION
                schema=workflow.TABLE_AUTHOR if ordered else workflow.GUIDED_AUTHOR
            thresholds=spec['protocol']==workflow.THRESHOLD_PROTOCOL and n>1
            if thresholds:
                points=source_thresholds.catalogue(spec['public_task'],statements)
                instruction=source_thresholds.INSTRUCTION
                schema=source_thresholds.author_schema(points,workflow.TABLE_AUTHOR)
            path=folder/'calls'/('shared-main.json' if n==1 else arm+'-main.json')
            author=call(path,packet,workflow.SYSTEM,instruction,schema)
            paths.add(path)
            bound_rows=spec['protocol']==workflow.BOUND_TABLE_PROTOCOL and n>1
            if thresholds:
                code,links,trace=source_thresholds.render(author,points,statements)
            elif bound_rows:
                code,links,trace=workflow.render_bound_rows(author,spec['public_task'],statements)
            else:
                code=guide.render_table(author,statements)[0] if ordered and n>1 else submission_text(author['code'])
            previous=read(branch/'snapshot.json')
            if thresholds or bound_rows:
                verify(read(branch/'time-conditions.json')==trace,branch,'시간 원문과 경계 처리')
                verify(previous['links']==links,branch,'실행 코드의 원문 인용')
            verify(previous['code']==code and previous['sha256']==digest(code) and previous['plan']==author['plan']
                   and previous['answer_batches']==[a['batch'] for a in answers],branch,'메인 코드와 수신한 답변')
            proposals=set(author['questions'])
            earlier=[]
            for i,view in enumerate(common.VIEWS,1):
                path=folder/'calls'/f'{arm}-review-{i}.json'
                packet=dict(base,메인의_계획=author['plan'],검토할_코드=code)
                if arm=='self' and earlier:
                    packet['직전_자기검토']=earlier
                system=(f'당신은 독립 검토자 {i}입니다. ' if arm=='multi' else '당신은 메인 개발자입니다. 스스로 검토하세요. ')+view
                review=call(path,packet,system,workflow.CHECK+'\n'+guide.REVIEW_INSTRUCTION if guided else workflow.CHECK,
                            workflow.GUIDED_REVIEW if guided else workflow.REVIEW)
                paths.add(path)
                earlier.append(review)
                proposals.update(review['questions'])
                proposals.update(q for q,choice in review.get('decisions',{}).items() if choice==guide.ASK)
            if (branch/'questions.json').is_file():
                requested=[g['question'] for g in read(branch/'questions.json')['groups']]
                verify(all(q in {p.strip() for p in proposals} for q in requested),branch,'실제 제안된 질문')
                for a in state['answers']:
                    if a['arm']!=arm or a['batch']!=n:
                        continue
                    verify(a['questions']==requested,branch,'답변의 대상 질문')
                    if a['source']=='delegated_policy_card':
                        strict_scope='operator_scope' in spec
                        text,parts,tags=operator.scoped_response(requested,precise=ordered or strict_scope,strict=strict_scope)
                        verify((a['text'],a['scoped_replies'],a['sources_by_question'])==(text,parts,tags),branch,'질문 범위와 대리 답변')
                    batches+=1
    verify(paths==set(run.glob('round-*/calls/*.json')),run,'기록된 실제 호출 수')
    return len(paths),batches


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',type=Path,nargs='+')
    for directory in parser.parse_args().runs:
        total,received=audit(directory)
        print(directory.name,f'호출 {total}개, 답변 {received}묶음 재생 일치')
