"""Check the global seal first, execute the new submissions in isolation, then match them with forecasts."""
from collections import Counter
import json

from run import (LAB, PREVIOUS, ROOT, STATE_PATH, SIZES, common_packet, content_hash,
                 folder, freeze, read)
from backend.allocation_repair import apply_edits
from experiments.scoped_transfer import bound_edits, evidence_choices
from score_pairs import correct, evaluate, result_kind


def verify_seals(design):
    sealed = read(ROOT / 'sealed.json')
    if content_hash(ROOT / 'design.json') != sealed['design']:
        raise ValueError('Experiment design differs from sealed design')
    expected = {str(folder(s, a, role).relative_to(ROOT))
                for s in design['seeds'] for a in ('A','B') for role in ('edit','predict')}
    if set(sealed['runs']) != expected:
        raise ValueError('All six pairs of submissions are required before scoring')
    for path, expected_hash in design['fingerprint'].items():
        if content_hash(LAB / path) != expected_hash:
            raise ValueError(f'Frozen file changed: {path}')
    for path, digests in sealed['runs'].items():
        dest = ROOT / path
        receipt = read(dest / 'receipt.json')
        if content_hash(dest / receipt['output']) != digests['output'] or content_hash(dest / 'receipt.json') != digests['receipt']:
            raise ValueError(f'Submission changed: {path}')
        if 'edit_log_sha256' in receipt and content_hash(dest / 'edit-log.json') != receipt['edit_log_sha256']:
            raise ValueError(f'Edit log changed: {path}')
        for key, checksum in receipt['calls'].items():
            if content_hash(dest / 'calls' / (key+'.json')) != checksum:
                raise ValueError(f'Model response changed: {path}')


def first_request(dest):
    receipt = read(dest / 'receipt.json')
    first = next(iter(receipt['calls']))
    return read(dest / 'calls' / (first+'.json'))['request']


def verify_proposal(dest, history, initial, code):
    attempts = read(dest / 'edit-log.json')
    last = attempts[-1]
    if last['outcome'] not in ('applied','no-edit'):
        if code != initial:
            raise ValueError('A rejected edit unexpectedly changed the submission')
        return
    raw = read(dest / 'calls' / (last['call']+'.json'))
    proposed = json.loads(raw['text'])['edits']
    if proposed != last['edits']:
        raise ValueError('Accepted edit differs from the model response')
    updated = apply_edits(initial, bound_edits({'edits': proposed}, evidence_choices(history)), history, ['abc-1'])
    if updated != code:
        raise ValueError('Replaying accepted edit failed to reconstruct the submitted code')


def main():
    design = read(ROOT / 'design.json')
    verify_seals(design)
    keys = read(ROOT / 'evaluator/key.json')
    state = read(STATE_PATH)
    previous_seal = read(PREVIOUS / 'sealed-all.json')
    per_run = []
    per_input = []
    use = {r: Counter() for r in ('edit','predict')}
    behavior = {}
    outcomes = {'허용': True, '거부': False}
    cross = Counter()
    group_for = {(True,True): 'both_correct', (True,False): 'prediction_only',
                 (False,True): 'code_only', (False,False): 'neither_correct'}
    for seed in design['seeds']:
        for side in ('A','B'):
            writer = folder(seed, side, 'edit')
            predictor = folder(seed, side, 'predict')
            previous = PREVIOUS / 'runs/upload' / str(seed) / side
            req, pred_req = first_request(writer), first_request(predictor)
            previous_log = read(previous / 'submission.json')
            previous_req = read(previous / 'calls' / (previous_log['attempts'][0]['call']+'.json'))['request']
            if req != previous_req:
                raise ValueError('Writer received a different request from the previous study')
            if req['messages'][1] != pred_req['messages'][1]:
                raise ValueError('Reader and writer did not receive identical public material')
            for field in ('model','temperature','top_p','top_k','seed','max_tokens','chat_template_kwargs'):
                if req[field] != pred_req[field]:
                    raise ValueError(f'Sampling setting differs between arms: {field}')
            text = (writer / 'solution.py').read_text()
            pred = read(predictor / 'predictions.json')
            verify_proposal(writer, common_packet(state, side)['dialogue'], state['code'], text)
            signature = content_hash(writer / 'solution.py')
            previous_sig = previous_seal['submissions'][f'upload/{seed}/{side}']
            if content_hash(previous / 'solution.py') != previous_sig:
                raise ValueError('Historical submission changed')
            if signature not in behavior:
                behavior[signature] = evaluate(text, state['function'], [[size] for size in SIZES])
            receipt = read(writer / 'receipt.json')
            for label, dest in [('edit',writer),('predict',predictor)]:
                data = read(dest / 'receipt.json')
                use[label].update(data['usage'])
                use[label]['calls'] += len(data['calls'])
            checks = []
            for size, actual in zip(SIZES, behavior[signature]):
                target = keys[side][str(size)]
                choice = pred[str(size)] if pred is not None else '출력 무효'
                predicted_ok = choice in outcomes and outcomes[choice] is target
                executed_ok = correct(actual, target)
                group = group_for[predicted_ok, executed_ok]
                cross[group] += 1
                case = dict(seed=seed, policy=side, size=size, expected=target, prediction=choice,
                            returned=actual['value'], error=actual['error'], executed_lines=actual['lines'],
                            code_status=result_kind(actual,target), prediction_correct=predicted_ok,
                            code_correct=executed_ok, result=group)
                checks.append(case)
                per_input.append(case)
            per_run.append(dict(seed=seed,policy=side,prediction_all=all(r['prediction_correct'] for r in checks),
                                code_all=all(r['code_correct'] for r in checks),edit_status=receipt['status'],
                                code_matches_original=signature==previous_sig))
    paired = []
    for seed in design['seeds']:
        sides = [r for r in per_input if r['seed']==seed]
        boundary = [r for r in sides if r['size']==16]
        controls = [r for r in sides if r['size']!=16]
        paired.append(dict(seed=seed,
            prediction_boundary=all(r['prediction_correct'] for r in boundary),
            execution_boundary=all(r['code_correct'] for r in boundary),
            prediction_controls=all(r['prediction_correct'] for r in controls),
            execution_controls=all(r['code_correct'] for r in controls)))
    result=dict(seal=content_hash(ROOT/'sealed.json'),cross_table=dict(cross),per_run=per_run,
                per_input=per_input,policy_flip=paired,usage={r:dict(counts) for r,counts in use.items()})
    freeze(ROOT/'evaluator/results.json',result)
    print(json.dumps({'matrix':dict(cross),'runs':per_run,'usage':result['usage']},ensure_ascii=False))


if __name__=='__main__':
    main()

