"""Apply an evidence check to the final P4 edit as an atomic, score-blind transaction."""
import argparse
import ast
from pathlib import Path

from experiments import festival_protocol as base, festival_refinement as refinement
from experiments.local_transport import local_server, locked_output, read
from experiments.project_review import freeze, publish


def behavior_lines(path, source):
    lines = refinement.executable(path, source)
    if not path.endswith(('.py', '.pyw')):
        return lines
    try:
        tree = ast.parse(source)
    except (ValueError, SyntaxError, RecursionError):
        return set()
    text = source.splitlines()
    declarations = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)
    return lines - {text[node.lineno - 1].strip() for node in ast.walk(tree) if isinstance(node, declarations)}


def decide(before, proposed, facts, bindings, prior_issues=()):
    # The author check uses one flag for absent lines on both present and changed claims.
    # Recheck that flag per binding so an unverified old claim does not discard a supported new edit.
    issues = [issue for issue in prior_issues if issue != 'missing_executable_line']
    credited, unverified = set(), []
    if sorted(b['reply'] for b in bindings) != sorted(facts):
        issues.append('reply_coverage')
    for binding in bindings:
        status, name, line = binding['status'], binding['file'], binding['line'].strip()
        if status == 'open':
            unverified.append(binding['reply'])
            continue
        in_candidate = bool(line and line in behavior_lines(name, proposed[name]))
        if status == 'changed':
            if not in_candidate or line in behavior_lines(name, before[name]):
                issues.append('changed_behavior_unverified')
            else:
                credited.add(name)
        elif not in_candidate:
            unverified.append(binding['reply'])
    changed = {name for name in before if proposed[name] != before[name]}
    if facts and changed and unverified and not credited:
        issues.append('unresolved_reply_and_unsupported_edit')
    hold = bool(issues and changed)
    return (before if hold else proposed), dict(held=hold, issues=sorted(set(issues)), unverified=unverified,
                                               changed_files=sorted(changed), evidenced_files=sorted(credited))


def finalize(out):
    state = read(out / 'state.json')
    info = state['arms']['p4']
    if info['status'] not in base.TERMINAL or info['version'] != 2:
        raise ValueError('담당자 답변에 대한 최종 작성·검토가 끝나야 적용할 수 있습니다.')
    previous, proposal = (read(out/'p4'/f'v{i}'/'snapshot.json') for i in (1, 2))
    attempt = proposal['attempts'][-1]
    replies = state['answers']
    facts = list(dict.fromkeys(s.strip() for a in replies for s in a['text'].splitlines() if s.strip()))
    files, decision = decide(previous['files'], proposal['files'], facts, attempt['bindings'], attempt['issues'])
    status = 'held_for_review' if decision['held'] else 'open_evidence' if decision['unverified'] else info['status']
    folder = out/'guarded'
    folder.mkdir(exist_ok=True)
    freeze(folder/'receipt.json', dict(status=status, **decision, author_call=proposal['author_call'],
                                      previous_sha256=previous['sha256'], proposed_sha256=proposal['sha256'],
                                      retained_sha256=base.core.digest(files), additional_model_calls=0, additional_tokens=0))
    publish(folder, 'p4-guarded', files)
    return files, read(folder/'receipt.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    parser.add_argument('--parent', type=Path, help='P3 첫 검토에서 시작할 때 지정합니다.')
    parser.add_argument('--answer-file', type=Path)
    parser.add_argument('--port', type=int, default=18768)
    args = parser.parse_args()
    with locked_output(args.out):
        path = args.out/'state.json'
        state = read(path) if path.exists() else None
        if not state and not args.parent:
            parser.error('새 실행을 시작하려면 --parent로 P3 첫 검토가 있는 폴더를 지정하세요.')
        if args.answer_file and (not args.parent or (state and state['arms']['p4']['status'] in base.TERMINAL)):
            parser.error('답변은 P3 원본과 답변 대기 중인 P4 실행에 연결하세요.')
        if args.parent and (not state or state['arms']['p4']['status'] not in base.TERMINAL):
            with local_server(args.port, read(args.parent/'design.json')['model']):
                state = refinement.stage(args.parent, args.out, args.answer_file.read_text() if args.answer_file else None, port=args.port)
        if state and state['arms']['p4']['status'] == 'awaiting_human':
            for q in read(args.out/'p4/v1/review.json')['questions']:
                print(' •', q['question'])
        else:
            print(finalize(args.out)[1])
