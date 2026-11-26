"""Run a public project through local author/reviewer cycles or reproduce a historical benchmark."""
import argparse
import hashlib
import json
import subprocess
import time
from functools import partial
from pathlib import Path
from urllib.request import urlopen

from experiments import local_transport as transport
from experiments.local_transport import MODEL, compact, locked_output, read
from experiments.local_baseline import BENCHMARK, ROOT, SECONDS_ADAPTER, SECONDS_CONTRACT, generate, submission_text
from experiments.monitor_pilot import FORMAT, PERSPECTIVES, REVIEW_TASK, SEEDS, msg, parsed_feedback, save


IDS = ('A', 'B', 'C')
ROUTING = {'reviewer_answers': 'none',
           'flow': 'A/B/C submit all questions and feedback to D; D consolidates for the main. No external operator replies.'}
MAIN = '당신은 예약 시스템의 Python 개발자입니다. 직접 질문하지 않고 주어진 정보로 전체 함수를 구현합니다.'
SUBMIT = ('담당자에게 직접 질문하지 마세요. 미확정 사항은 합리적으로 가정하고, 표준 라이브러리만 쓰는 '
          '실행 가능한 전체 Python 함수를 하나의 코드 블록으로 제출하세요.')
EDITOR = ('당신은 검토 편집자 D입니다. 현재 코드와 A·B·C 의견을 모두 읽고 겹치는 지적은 한 항목으로 '
          '합치세요. 각 항목에 출처 ID를 붙이고 세 출처를 모두 다루세요. 질문이 없는 의견, 계속 진행 의견, '
          '서로 다른 지적과 의견 충돌도 보존하세요. 확인되지 않은 해석은 가설로 표시하세요. '
          '새 정책·새 지적·코드를 만들지 말고, 메인에게 전달할 피드백을 간결하게 정리하세요.')
GROUP = {'type': 'object', 'properties': {
    'sources': {'type': 'array', 'items': {'type': 'string', 'enum': list(IDS)}, 'minItems': 1, 'maxItems': 3},
    'summary': {'type': 'string'}}, 'required': ['sources', 'summary'], 'additionalProperties': False}
MERGE_FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'digest', 'strict': True, 'schema': {
    'type': 'object', 'properties': {'groups': {'type': 'array', 'items': GROUP, 'minItems': 1, 'maxItems': 6}},
    'required': ['groups'], 'additionalProperties': False}}}


def public_brief():
    brief = (BENCHMARK/'agent/TASK_BASIC.md').read_text().split('\n\n', 2)[2]
    return SECONDS_CONTRACT + '\n\n' + brief.replace('결과를 바꿀 수 있는 운영 기준이 필요하면 담당자에게 구체적으로 질문할 수 있습니다. ', '')


def recorded(path, role, system, user, seed, limit, port, fmt=None, model=MODEL):
    return transport.recorded(path,role,system,user,seed,limit,port,fmt,model,generator=generate)


def current_context(brief, code, decisions):
    return compact({'공개 과제': brief, '현재 코드': code, '이전 회차까지 전달된 담당자 답': decisions})


def review(d, cycle, brief, code, decisions, seed, port):
    context = current_context(brief, code, decisions)
    rows = {}
    for who, perspective in zip(IDS, PERSPECTIVES):
        c = recorded(d/f'{cycle}-{who}.json', who, '당신은 메인 코드의 독립 감시자입니다.',
                     context + '\n' + perspective + '\n' + REVIEW_TASK, seed, 320, port, FORMAT)
        rows[who] = parsed_feedback(c)
    save(d/f'{cycle}-reviews.json', rows)
    print('REVIEWS', seed, cycle, flush=True)
    return rows


def editor_groups(raw, reviews):
    try:
        groups = json.loads(raw)['groups']
    except (ValueError, KeyError, TypeError):
        groups = []
    valid = [g for g in groups if isinstance(g, dict) and isinstance(g.get('sources'), list)
             and g['sources'] and all(s in IDS for s in g['sources']) and isinstance(g.get('summary'), str)
             and g['summary'].strip()] if isinstance(groups, list) else []
    covered = {s for g in valid for s in g['sources']}
    missing = [s for s in IDS if s not in covered]
    for s in missing:
        valid.append({'sources': [s], 'summary': compact(reviews[s])})
    return valid, missing


def run(out, port):
    brief = public_brief()
    for seed in SEEDS:
        d = out/str(seed)
        d.mkdir(exist_ok=True)
        recorded(d/'0-main.json', 'main', MAIN, brief+'\n\n'+SUBMIT, seed, 1500, port)
    # All seeds share this protocol. Within a seed each cycle reads the preceding submission.
    for seed in SEEDS:
        d = out/str(seed)
        code = submission_text(read(d/'0-main.json')['text'])
        decisions = []
        for cycle in range(1, 4):
            reviews = review(d, cycle, brief, code, decisions, seed, port)
            answers = dict.fromkeys(IDS, '')
            rows = [dict(id=s, **reviews[s], operator_answer=answers[s]) for s in IDS]
            context = current_context(brief, code, decisions)
            editor = recorded(d/f'{cycle}-D.json', 'D', EDITOR, context+'\n세 감시 의견 원문\n'+compact(rows),
                              seed, 800, port, MERGE_FORMAT)
            groups, missing = editor_groups(editor['text'], reviews)
            exchanges = [dict(cycle=cycle, id=s, question=reviews[s]['question'],
                              feedback=reviews[s]['feedback'] if not reviews[s]['question'] else '',
                              operator_answer=answers[s]) for s in IDS if reviews[s]['question'] or answers[s]]
            packet = dict(groups=groups, questions_and_answers=exchanges)
            save(d/f'{cycle}-handoff.json', dict(packet=packet, verbatim_fallback_ids=missing))
            revision = recorded(d/f'{cycle}-main.json', 'main', MAIN, context+'\nD가 정리한 피드백\n'+compact(packet)
                                +'\n확정된 근거와 현재 코드를 대조해 필요한 부분만 수정하세요. '+SUBMIT,
                                seed, 1500, port)
            code = submission_text(revision['text'])
            print('SAVED', seed, cycle, flush=True)


def score(out):
    from backend.isolated import grade_isolated
    if not all((out/str(s)/'3-main.json').exists() for s in SEEDS):
        raise ValueError('모든 시드의 3회차 제출이 있어야 채점합니다.')
    for seed in SEEDS:
        for cycle in range(4):
            d = out/str(seed)
            code = submission_text(read(d/f'{cycle}-main.json')['text'])
            report = grade_isolated(code+SECONDS_ADAPTER, BENCHMARK, 'cancellation_basic')
            save(d/f'{cycle}-score.json', dict(code_sha256=hashlib.sha256(code.encode()).hexdigest(), report=report))
            print('SCORE', seed, cycle, report['score'], flush=True)


def local_server(port,model=MODEL):
    return transport.local_server(port,model,health_check=urlopen)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', type=Path)
    p.add_argument('--port', type=int, default=18756)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--project', type=Path, help='Public JSON with brief and editable text files')
    mode.add_argument('--human-intervention', action='store_true', help='Main author, three question-only monitors and real human replies')
    mode.add_argument('--legacy-review-cycles', action='store_true', help='Reproduce the historical three cycles without operator replies')
    mode.add_argument('--verified', action='store_true', help='Compare revisions using executable feedback')
    mode.add_argument('--candidates', action='store_true', help='Compare verified A/B/C proposals selected by D')
    mode.add_argument('--blind-candidates', action='store_true', help='Select from source text, then grade the sealed batch')
    mode.add_argument('--serial-revisions', action='store_true', help='Apply requirement-linked edits sequentially, then grade')
    mode.add_argument('--rule-table-revisions', action='store_true', help='Reproduce the whole-table revision comparison')
    mode.add_argument('--finalize-source', type=Path, metavar='SEALED_RUN',
                      help='Review the two public time references after a sealed source-edit run')
    mode.add_argument('--public-clock-revisions', action='store_true',
                      help='Run the source and public-clock reviews together before any evaluation')
    p.add_argument('--seal-only', action='store_true', help='Save the source-edit submissions without grading them')
    p.add_argument('--shared-inputs-from', type=Path, help='Pair a source-edit run on the raw drafts and A calls of a rule-table run')
    p.add_argument('--seed', type=int, help='Seed for the human-intervention comparison (default 131 for a new run)')
    p.add_argument('--policy-file', type=Path, help='Natural-language policy supplied by the operator at the start')
    p.add_argument('--answer-file', type=Path, help='Plain-text human answer for the waiting question batch')
    p.add_argument('--reply-to', type=int, help='Question batch number to which the human is replying')
    p.add_argument('--reply-arm', choices=('self','multi'), help='Recipient of a direct natural-language reply')
    p.add_argument('--author-model', help='Local GGUF model for the main author and self-review')
    p.add_argument('--review-models', nargs=3, help='Local GGUF paths for the three independent reviewers')
    p.add_argument('--operator-card', action='store_true', help='Use the authorized operator proxy to answer only the pending questions')
    intervention_style=p.add_mutually_exclusive_group()
    intervention_style.add_argument('--question-guide', action='store_true', help='Use a review question form and in-code policy citations')
    intervention_style.add_argument('--ordered-rules', action='store_true', help='Use the same review form and let the author specify ordered conditions and a fallback')
    intervention_style.add_argument('--source-thresholds', action='store_true', help='Bind time comparisons to the public notice and received natural-language policies')
    intervention_style.add_argument('--bind-authored-times', action='store_true', help="Use the existing ordered-rule author form and bind its time conditions before each review")
    p.add_argument('--draft-from', type=Path, help='Use the identical first author call from a matched free-question or ordered-rule run')
    args = p.parse_args()
    selected_old = (args.verified or args.candidates or args.blind_candidates or args.serial_revisions
                    or args.rule_table_revisions or args.public_clock_revisions or args.finalize_source is not None
                    or args.legacy_review_cycles)
    historical=args.out/'design.json'
    saved_protocol=read(historical).get('protocol') if historical.is_file() else None
    from backend.project_review import PROTOCOLS as project_protocols
    if args.project is not None or saved_protocol in project_protocols:
        if (selected_old or args.human_intervention or args.seal_only or args.shared_inputs_from or args.question_guide
                or args.ordered_rules or args.source_thresholds or args.bind_authored_times or args.policy_file or args.operator_card or args.draft_from):
            p.error('일반 프로젝트는 공개 명세와 해당 실행에 직접 전달한 자연어 답변을 사용합니다.')
        from experiments.project_review import run as run_project
        run_project(args.out,read(args.project) if args.project else None,args.seed,args.author_model,args.review_models,
                    args.port,args.reply_arm,args.reply_to,args.answer_file)
        return
    if args.author_model or args.review_models:
        p.error('역할별 모델 지정은 --project 실행에서 사용합니다.')
    if not (saved_protocol or selected_old or args.human_intervention or (args.out/'routing.json').exists()
            or args.ordered_rules or args.question_guide or args.source_thresholds or args.bind_authored_times):
        p.error('새 작업은 --project 공개명세.json을 지정하세요. 기존 예약 기준선은 --human-intervention으로 실행합니다.')
    human = args.human_intervention or (not selected_old and not (args.out/'routing.json').exists())
    if human:
        if args.seal_only or args.shared_inputs_from is not None:
            p.error('사람에게 묻는 실험은 그 실행에 제공된 자연어와 코드만 사용합니다.')
        if (args.answer_file is None) != (args.reply_to is None):
            p.error('--answer-file과 --reply-to를 함께 지정하세요.')
        if args.operator_card and args.answer_file is not None:
            p.error('직접 답변과 진행자 대리 응답 중 이번 실행에 쓸 방식을 선택하세요.')
        if saved_protocol=='human-intervention-v1':
            if args.question_guide or args.ordered_rules or args.source_thresholds or args.bind_authored_times or args.draft_from or args.reply_arm:
                p.error('공동 답변 기록에는 방식별 질문 옵션을 적용할 수 없습니다.')
            from experiments.human_intervention import run as run_matched
            run_matched(args.out,args.port,args.seed,args.policy_file,args.reply_to,args.answer_file,args.operator_card)
        else:
            from experiments.scoped_intervention import run as run_intervention
            run_intervention(args.out,args.port,args.seed,args.policy_file,args.reply_to,args.answer_file,
                             args.operator_card,args.reply_arm,args.question_guide,args.draft_from,args.ordered_rules,args.source_thresholds,args.bind_authored_times)
        return
    if args.operator_card or args.question_guide or args.ordered_rules or args.source_thresholds or args.bind_authored_times or any(item is not None for item in (args.seed,args.policy_file,args.answer_file,args.reply_to,args.reply_arm,args.draft_from)):
        p.error('담당자 입력 옵션은 --human-intervention 실행에서 사용합니다.')
    if args.shared_inputs_from is not None and not (args.serial_revisions or args.public_clock_revisions):
        p.error('--shared-inputs-from은 원본 보존 방식의 공통 초안과 A 응답용입니다.')
    if args.seal_only and not (args.serial_revisions or args.rule_table_revisions):
        p.error('--seal-only는 원본 보존 또는 전체 규칙표 비교의 생성 단계에 사용합니다.')
    args.out.mkdir(parents=True, exist_ok=True)
    routing = args.out/'routing.json'
    comparison = (args.verified or args.candidates or args.blind_candidates or args.serial_revisions
                  or args.rule_table_revisions or args.finalize_source is not None or args.public_clock_revisions)
    if comparison:
        if routing.exists():
            p.error('기존 3회차 실험 폴더입니다. 조정한 실험은 새 폴더에서 실행하세요.')
    elif (args.out/'design.json').exists():
        p.error('실험 설계가 기록된 폴더입니다. 실행 방식을 확인하세요.')
    elif routing.exists() and read(routing) != ROUTING:
        raise ValueError('기존 결과의 전달 조건이 다릅니다. 새 출력 폴더를 사용하세요.')
    elif not routing.exists():
        save(routing, ROUTING)
    if not comparison and (args.out/'timing.json').exists() and all((args.out/str(s)/f'{n}-score.json').exists()
                                                 for s in SEEDS for n in range(4)):
        print('완료된 실행 기록이 있습니다.', args.out)
        return
    prepare, evaluate = None, None
    if args.public_clock_revisions:
        from experiments.policy_finalization import prepare_pipeline, evaluate_seal
        prepare = partial(prepare_pipeline,args.out,args.port,args.shared_inputs_from)
        evaluate = partial(evaluate_seal,args.out)
    elif args.finalize_source is not None:
        from experiments.policy_finalization import prepare_seal, evaluate_seal
        prepare = partial(prepare_seal,args.out,args.port,args.finalize_source)
        evaluate = partial(evaluate_seal,args.out)
    elif args.serial_revisions or args.rule_table_revisions:
        from experiments.serial_revisions import prepare_seal, evaluate_seal
        prepare = partial(prepare_seal,args.out,args.port,args.serial_revisions,args.shared_inputs_from)
        evaluate = partial(evaluate_seal,args.out,args.serial_revisions)
    if evaluate and (args.out/'submissions.json').exists():
        if not args.seal_only:
            evaluate()
        return
    start = time.monotonic()
    with local_server(args.port):
        if prepare:
            prepare()
        elif comparison:
            if args.blind_candidates:
                from experiments.blind_candidates import run as run_comparison
            elif args.candidates:
                from experiments.candidate_cycles import run as run_comparison
            else:
                from experiments.verified_cycles import run as run_comparison
            run_comparison(args.out, args.port)
            return
        else:
            run(args.out, args.port)
    if evaluate:
        if not args.seal_only:
            evaluate()
        return
    score(args.out)
    save(args.out/'timing.json', {'elapsed_seconds': round(time.monotonic()-start, 2)})


if __name__ == '__main__':
    main()
