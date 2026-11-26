"""Researcher-side comparison of final saved versions in paired time-condition experiments."""
import argparse
import difflib
import hashlib
import inspect
from collections import Counter
from pathlib import Path

from backend.isolated import grade_isolated
from experiments import intervention_audit, question_guide as guide, rule_edits, scoped_intervention as workflow, source_thresholds
from experiments.blind_candidates import digest
from experiments.intervention_research import research_directory
from experiments.local_baseline import BENCHMARK, SECONDS_ADAPTER
from experiments.monitor_cycles import read, save


def first_exchange(run,arm,state):
    path=run/'round-001'/arm/'questions.json'
    groups=read(path)['groups'] if path.exists() else []
    replies=[a['text'] for a in state['answers'] if a['arm']==arm and a['batch']==1]
    return groups,replies


def verdicts(report):
    return {r['id']:('미판정' if r['error'] else '정답' if r['passed'] else '오답') for r in report['results']}


def latest(run,arm,state):
    info=state['arms'][arm]
    if info['status'] not in ('completed','incomplete_limit'):
        raise ValueError(f'{run.name}/{arm}의 전체 검토가 끝나지 않았습니다.')
    round_name=f"round-{info['version']:03d}"
    branch=run/round_name/arm
    directory=research_directory(run)
    result=read(directory/round_name/arm/'grade.json')
    if result['report'] is None:
        raise ValueError(f'{run.name}/{arm}의 점수를 확인할 수 없습니다.')
    grade=result['report']
    summary=read(directory/'summary.json')
    versions=[r for r in summary['versions'] if r['arm']==arm]
    outcomes=verdicts(grade)
    counts=Counter(outcomes.values())
    if len(outcomes)!=grade['total'] or counts['정답']!=grade['score']:
        raise ValueError('문항별 판정과 합계가 다릅니다.')
    answers=[a for a in state['answers'] if a['arm']==arm]
    usage=summary['usage'][arm]
    snapshots=dict(status=info['status'],version=info['version'],code_sha256=result['sha256'],
                   grade_version=grade['benchmark_version'],policy_sha256=grade['policy_sha256'],total=grade['total'],
                   correct=counts['정답'],wrong=counts['오답'],unanswered=counts['미판정'],
                   score_history=[r['score'] for r in versions],returned_history=[r['returned'] for r in versions],
                   categories=grade['categories'],calls=usage['calls'],tokens=usage['tokens'],
                   questions=usage['questions'],question_batches=usage['question_batches'],
                   human_replies=sum(a['source']=='human' for a in answers),
                   proxy_replies=sum(a['source']=='delegated_policy_card' for a in answers),
                   received_policy_decisions=sorted(workflow.sent_facts(state,arm)&workflow.TASK_DECISIONS))
    review=read(branch/'review.json')
    snapshots['last_review']=dict(author_complete=read(branch/'snapshot.json')['main_complete'],
                                  reviewers_requesting_revision=sum(r['needs_code_revision'] for r in review['reviews']),
                                  all_received_decisions_cited=review['linked'],missing_decisions=review['missing_delivered_facts'],
                                  questions_to_operator=(branch/'questions.json').is_file())
    trace=branch/'time-conditions.json'
    if trace.exists():
        entries=read(trace)
        snapshots['last_time_conditions']=dict(conditions=len(entries),missing_limit=sum('seconds' not in e for e in entries),
                                              unresolved_equality=sum(e['equality'] is None for e in entries))
    return snapshots,outcomes


def fixed_rows(control,candidate,arm,state,old_outcomes):
    """Apply the compiler to the exact rows in the control, without a new author or any model feedback."""
    version=state['arms'][arm]['version']
    if version<2:
        return None
    folder=control/f'round-{version:03d}'
    before=read(folder/arm/'snapshot.json')
    authored=rule_edits.decode(read(folder/'calls'/f'{arm}-main.json')['text'],workflow.TABLE_AUTHOR)
    spec=read(control/'design.json')
    statements=guide.citable_sentences([spec['initial_policy'],*[a['text'] for a in state['answers']
                                                               if a['arm']==arm and a['batch']<version]])
    if authored is None or guide.render_table(authored,statements)[0]!=before['code']:
        raise ValueError('대조군의 마지막 코드를 동일 규칙으로 재생할 수 없습니다.')
    code,_,trace=workflow.render_bound_rows(authored,spec['public_task'],statements)
    output=research_directory(candidate)/'same-author-rows'/arm
    output.mkdir(parents=True,exist_ok=True)
    file=output/'grade.json'
    if file.exists():
        stored=read(file)
        if stored['code_sha256']!=digest(code) or stored['original_sha256']!=before['sha256']:
            raise ValueError('동일 행 대조의 저장된 코드가 달라졌습니다.')
        report=stored['report']
    else:
        report=grade_isolated(code+SECONDS_ADAPTER,BENCHMARK,'cancellation_basic')
        save(file,dict(code_sha256=digest(code),original_sha256=before['sha256'],report=report))
    save(output/'source.json',dict(code=code,conditions=trace,version=version))
    patch=difflib.unified_diff(before['code'].splitlines(True),code.splitlines(True),'대조군 마지막 코드','같은 규칙 행에 시간 조건만 적용')
    (output/'change.diff').write_text(''.join(patch))
    original_grade=read(research_directory(control)/folder.name/arm/'grade.json')['report']
    outcomes=verdicts(report)
    if outcomes.keys()!=old_outcomes.keys() or report['policy_sha256']!=original_grade['policy_sha256']:
        raise ValueError('동일 행 대조의 문항 또는 정책이 다릅니다.')
    counts=Counter(outcomes.values())
    changes=Counter(old_outcomes[i]+' → '+outcomes[i] for i in outcomes)
    return dict(correct=counts['정답'],wrong=counts['오답'],unanswered=counts['미판정'],
                transitions=dict(sorted(changes.items())),code_sha256=digest(code))


def paired(control,candidate,include_fixed_rows=False):
    left,right=read(control/'design.json'),read(candidate/'design.json')
    matching=('seed','model','public_task','initial_policy','max_versions','author_token_limit','reviewer_token_limit','operator_scope')
    if (left['protocol']!=workflow.TABLE_PROTOCOL or right['protocol'] not in (workflow.THRESHOLD_PROTOCOL,workflow.BOUND_TABLE_PROTOCOL) or
            any(left[k]!=right[k] for k in matching)):
        raise ValueError('같은 시드와 입출력 조건으로 짝지은 두 실행이 필요합니다.')
    shared='round-001/calls/shared-main.json'
    if read(control/shared)!=read(candidate/shared):
        raise ValueError('같은 초안 호출 기록이 아닙니다.')
    states=[read(path/'state.json') for path in (control,candidate)]
    result=dict(control=control.name,candidate=candidate.name,candidate_protocol=right['protocol'],seed=left['seed'],arms={})
    for arm in workflow.ARMS:
        old,old_outcomes=latest(control,arm,states[0])
        new,new_outcomes=latest(candidate,arm,states[1])
        if (old_outcomes.keys()!=new_outcomes.keys() or old['policy_sha256']!=new['policy_sha256']
                or old['grade_version']!=new['grade_version']):
            raise ValueError('비교 문항 또는 채점 기준이 다릅니다.')
        first_old=first_exchange(control,arm,states[0])
        first_new=first_exchange(candidate,arm,states[1])
        changes=Counter(old_outcomes[k]+' → '+new_outcomes[k] for k in old_outcomes)
        result['arms'][arm]=dict(control=old,candidate=new,net=new['correct']-old['correct'],transitions=dict(sorted(changes.items())),
                                 same_first_questions=first_old[0]==first_new[0],same_first_reply=first_old[1]==first_new[1])
        first_revision=f'round-002/calls/{arm}-main.json'
        if all((p/first_revision).exists() for p in (control,candidate)):
            first_control,first_candidate=[read(p/first_revision) for p in (control,candidate)]
            result['arms'][arm]['same_first_revision_request']=first_control['request']==first_candidate['request']
            result['arms'][arm]['same_first_revision_output']=first_control['text']==first_candidate['text']
        if include_fixed_rows and right['protocol']==workflow.THRESHOLD_PROTOCOL:
            result['arms'][arm]['same_author_rows']=fixed_rows(control,candidate,arm,states[0],old_outcomes)
    result['audit']={}
    for path in (control,candidate):
        calls,batches=intervention_audit.audit(path)
        result['audit'][path.name]=dict(recorded_calls=calls,answer_batches=batches)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair',nargs=2,type=Path,action='append',required=True,metavar=('CONTROL','CANDIDATE'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--same-author-rows',action='store_true',help='Grade the unmodified control row ordering with source-based thresholds offline')
    args=parser.parse_args()
    results=[paired(*pair,args.same_author_rows) for pair in args.pair]
    compiler_hash=hashlib.sha256(Path(source_thresholds.__file__).read_bytes()).hexdigest()
    save(args.output,dict(pairs=results,compiler_sha256=compiler_hash,
                          authored_rows_adapter_sha256=digest(inspect.getsource(workflow.render_bound_rows)),
                          endpoint='last saved, reviewed version per arm; status records submission separately'))
