"""Research-only comparison of two writers using identical recorded owner dialogues."""
import difflib
from collections import Counter
from pathlib import Path

from experiments import answer_fidelity_study as study, festival_mini as mini, three_cycle_report as original, three_cycle_study as old
from experiments.festival_report import select_cases, token_sum, write_csv
from experiments.local_transport import read
from experiments.project_review import freeze
from experiments.rule_cycle_report import stored_control


def verify_final_submissions(config):
    for task in config['projects']:
        for arm in config['roles']:
            if not (study.STUDY/'runs'/task/arm/'final.json').is_file():
                raise ValueError('모든 세 번째 제출을 고정한 뒤에 채점합니다.')
    for task in config['projects']:
        for arm in config['roles']:
            old.conduct(task, arm, 0, audit=True)
            study.run_arm(task, arm, 0, audit=True)


def local_generation(folder, locations):
    """The transport reuses a compatible request from the old run, otherwise it generates in this folder."""
    paths = [p for p in sorted((folder/'calls').glob('*.json')) if not any((d/p.name).is_file() for d in locations)]
    return [read(p) for p in paths]


def checked_baseline(task, arm, cycle, snapshot, selected, fixtures, measured, probes, archive):
    baseline, counts = original.grade(task, arm, cycle, snapshot, selected, fixtures, measured, probes)
    if baseline['cases'] != archive['cases'] or baseline['sha256'] != archive['sha256']:
        raise ValueError('같은 채점기로 재실행한 기준선과 종전 기록이 다릅니다.')
    return baseline, counts


def report():
    cfg = study.preregister()
    verify_final_submissions(cfg)
    benchmark = read(mini.CONFIG)
    archived = read(old.STUDY/'research/observations.json')['tasks']
    rows, items, audit, diffs, pilot_calls = [], [], {}, [], []
    latest_round = cfg['cycles']
    for task in cfg['projects']:
        fixtures = select_cases(benchmark, task)
        probes = benchmark['policy_probes_within_sample'][task]
        earlier, parent, prior, design, _ = old.load_public(task)
        parent_calls = [p/'calls' for p in (earlier, parent, prior)]
        seen_codes = {}
        audit[task] = {}
        for arm in ['solo', *cfg['roles']]:
            track = audit[task][arm] = {}
            selected, receipts = set(), []
            running = Counter()
            rounds = (0,) if arm == 'solo' else range(1, latest_round + 1)
            for n in rounds:
                held = physical = 0
                new_tokens = 0
                changes = []
                question_count = 0
                transcript = None
                if arm == 'solo':
                    before = after = stored_control(task, arm, parent, design)
                    raw = original.raw_calls(after['calls'], parent_calls)
                else:
                    old_folder = old.root(task, arm)/f'cycle-{n}'
                    folder = study.STUDY/'runs'/task/arm/f'cycle-{n}'
                    locations = [old_folder/'calls', *parent_calls]
                    intake = read(old_folder/'intake.json')
                    question_count = len(intake['questions'])
                    if question_count:
                        receipts.append(read(old_folder/'answer.json'))
                        selected.update(item for group in read(old_folder/'operator.json')['selections'] for item in group)
                    before = read(old_folder/'snapshot.json')
                    after = read(folder/'snapshot.json')
                    transcript = after['transcript_sha256']
                    if transcript != study.live.base.core.digest([intake['questions'], receipts]) or before['sha256'] != after['baseline_sha256']:
                        raise ValueError('짝지은 질문·회신·기준 코드의 식별값이 다릅니다.')
                    held = len(after['held_question_calls'])
                    if after['calls'][:held] != before['calls'][:held]:
                        raise ValueError('고정한 질문 또는 초안의 호출이 다릅니다.')
                    raw = original.raw_calls(after['calls'], [folder/'calls', *locations])
                    if {p.stem for p in (folder/'calls').glob('*.json')} != set(after['calls'][held:]):
                        raise ValueError('새 작성기·최종 검토의 호출 기록이 목록과 다릅니다.')
                    physical_raw = local_generation(folder, locations)
                    physical, new_tokens = len(physical_raw), token_sum(physical_raw)['total_tokens']
                    pilot = study.STUDY/'format-pilot/runs'/task/arm/f'cycle-{n}'
                    pilot_calls.extend(local_generation(pilot, locations))
                    changes = [dict(scope=record['scope'], **c) for record in after['writer']['answer_application'] for c in record.get('changes', [])]
                    for path, text in after['files'].items():
                        diffs.extend(difflib.unified_diff(before['files'][path].splitlines(), text.splitlines(),
                            fromfile=f'before/{task}/{arm}/cycle-{n}/{path}', tofile=f'after/{task}/{arm}/cycle-{n}/{path}', lineterm=''))
                reference = archived[task][arm][str(n)]
                baseline, old_counts = checked_baseline(task, arm, n, before, selected, fixtures, seen_codes, probes, reference)
                entry, now = original.grade(task, arm, n, after, selected, fixtures, seen_codes, probes)
                gained, lost, modified = original.differences(baseline['cases'], entry['cases'])
                costs = token_sum(raw)
                writer_keys = after.get('writer', {}).get('calls', [])
                old_keys = before.get('writer', {}).get('calls', [])
                running.update(**costs, calls=len(raw), questions=question_count, physical=physical, physically_generated_tokens=new_tokens)
                metrics = dict(task=task, arm=arm, cycle=n, before=old_counts['correct'], after=now['correct'], wrong=now['wrong'],
                               unanswered=now['unanswered'], unsupported=now['unsupported_returns'], probes=now['policy_probes'],
                               gained=len(gained), lost=len(lost), other_outcome_changes=len(set(modified)-set(gained)-set(lost)),
                               questions=question_count, calls=len(raw), writer_calls=len(writer_keys), added_writer_calls=len(writer_keys)-len(old_keys),
                               original_writer_requests=writer_keys==old_keys,
                               held=held, physical=physical, physically_generated_tokens=new_tokens, **costs, **{'cum_'+k:v for k,v in running.items()},
                               before_cum_tokens=reference['metrics']['cumulative_total_tokens'], status=after['status'])
                rows.append(metrics)
                track[str(n)] = dict(metrics=metrics, transcript_sha256=transcript, code_sha256=entry['sha256'],
                    reference_sha256=baseline['sha256'], received_policy_ids=sorted(selected), rules=entry['rules'],
                    unsupported_items=entry['unsupported_items'], gained=gained, lost=lost, modified=modified,
                    corrected_branches=changes, cases=entry['cases'])
                for case_id, case in entry['cases'].items():
                    prev = baseline['cases'][case_id]
                    items.append(dict(task=task, arm=arm, cycle=n, item=case_id, inputs=str(case['args']), expected=case['expected'],
                                      before=prev['actual'], before_status=prev['status'], after=case['actual'], after_status=case['status'],
                                      changed=case_id in modified))
    summary = []
    fields = ('before','after','wrong','unanswered','unsupported','probes','gained','lost','other_outcome_changes','questions',
              'calls','writer_calls','added_writer_calls','physical','physically_generated_tokens','cum_calls','cum_questions',
              'cum_prompt_tokens','cum_completion_tokens','cum_total_tokens','cum_physical','cum_physically_generated_tokens','before_cum_tokens')
    for arm in ('solo', *cfg['roles']):
        for n in ((0,) if arm == 'solo' else range(1,latest_round+1)):
            paired = [r for r in rows if (r['arm'],r['cycle'])==(arm,n)]
            summary.append(dict(arm=arm, cycle=n, **{f:sum(r[f] for r in paired) for f in fields},
                                same_writer_requests=all(r['original_writer_requests'] for r in paired)))
    out = study.STUDY/'research'
    out.mkdir(exist_ok=True)
    write_csv(out/'summary.csv', summary)
    write_csv(out/'by-project.csv', rows)
    write_csv(out/'items.csv', items)
    (out/'code-changes.diff').write_text('\n'.join(diffs)+'\n')
    auxiliary = [r for r in pilot_calls if r['role']=='main-answer-implementation']
    audit_pilot = dict(new_model_calls=len(pilot_calls), new_model_tokens=token_sum(pilot_calls),
                       answer_mapping_calls=len(auxiliary), answer_mapping_tokens=token_sum(auxiliary))
    freeze(out/'observations.json', dict(tasks=audit, summary=summary, exploration=audit_pilot))
    files=['summary.csv','by-project.csv','items.csv','code-changes.diff','observations.json']
    freeze(out/'manifest.json', dict(protocol=mini.checksum(study.STUDY/'manifest.json'),
           scoring=mini.checksum(Path(__file__)), previous_scoring=mini.checksum(old.STUDY/'research/manifest.json'),
           shared_grader=mini.checksum(Path(original.__file__)), artifacts={f:mini.checksum(out/f) for f in files}))
    for row in summary:
        print(row['arm'], row['cycle'], row['before'], row['after'], row['wrong'], row['unanswered'],
              row['gained'], row['lost'], row['before_cum_tokens'], row['cum_total_tokens'])
    print('pilot', audit_pilot)
