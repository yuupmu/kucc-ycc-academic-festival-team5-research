"""Report separately what the owner actually said and the exclusion planned if equality was asked."""
from trial import ARCHIVES, FIRST, LAB, OUT, freeze, read, sha

DEFER = 'NotImplementedError'


def measure(folder):
    report, owner = read(folder/'results.json'), read(folder/'owner-delivery.json')
    assert report['seal'] == sha(folder/'final-seal.json')
    assert read(folder/'final-seal.json')['owner'] == sha(folder/'owner-delivery.json')
    # Check verbatim what was delivered, not the private disposition of the proxy owner.
    # Neither run received an equality policy in the omission arm, even after its question.
    omitted_reply = owner['replies']['unmentioned']
    known_replies = {'0바이트 빈 파일은 거부합니다.', '네, 0바이트보다 크고 16바이트보다 작은 파일은 허용합니다.'}
    assert omitted_reply in known_replies
    xs = report['tested_inputs']
    cases = [row['args'][0] for row in read(LAB/'experiments/transfer100-20261126/evaluator/cases.json') if row['task']=='upload']
    stages = {}
    for label, values in report['outputs'].items():
        name = label.split('/')[0]
        boundary = {'include': True, 'exclude': False, 'unmentioned': DEFER}[name]
        seen = dict(zip(xs, values))
        def correct(x):
            return seen[x] == (boundary if x == 16 else 0 < x < 16)
        stages[label] = dict(behavior_at_15_16_17=[seen[x] for x in (15,16,17)],
                             received_policy_at_16=boundary, matches_received_on_20=sum(correct(x) for x in cases),
                             matches_received_on_38=sum(correct(x) for x in report['controls']),
                             matches_received_everywhere=all(correct(x) for x in report['integer_witnesses']),
                             official_inclusive_20=report['checks'][label]['official_inclusive_20'])
    return dict(sealed_outputs=report['seal'], source_results=sha(folder/'results.json'), reached_goal=report['passed'],
                stages=stages, questions=report['questions'], owner_replies=owner['replies'],
                differences=report['differences'], costs=report['costs'])


def main():
    result = {label: measure(folder) for label, folder in [('sentence_verification', FIRST), ('retained_writer', OUT)]}
    costs = {}
    for log in (OUT/'calls').glob('*.json'):
        candidates = [archive/log.name for archive in ARCHIVES]
        found = next((p for p in candidates if p.exists() and sha(p)==sha(log)), None)
        group = str(found.parent.relative_to(LAB)) if found else 'new local inference in retained writer'
        row = costs.setdefault(group, {'calls': 0, 'tokens': 0})
        row['calls'] += 1
        row['tokens'] += read(log)['usage']['total_tokens']
    assert sum(v['tokens'] for v in costs.values()) == result['retained_writer']['costs']['unique']['total_tokens']
    result['retained_writer']['reuse'] = costs
    result['counterfactual'] = 'The precommitted exclusion reply was never sent in the omission arm of either variant. The correct actual-evidence behavior at equality remained abstention. The separate hypothetical final-exclusion endpoint in each original results.json remains archived.'
    freeze(OUT/'received-policy-results.json', result)
    for k in ('sentence_verification','retained_writer'):
        print(k, {s:v['matches_received_on_20'] for s,v in result[k]['stages'].items()})


if __name__ == '__main__':
    main()
