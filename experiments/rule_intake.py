"""Independent, counterfactual elicitation over a public project. Hypotheses stay on the reviewer side."""
from experiments import festival_protocol as base
from experiments.festival_refinement import revision_view
from backend.structured_output import obj


LENSES = (
    'Identify a missing operational definition. Ask the owner to give the actual criterion, its reference point and boundary if these form one decision.',
    'Look for overlapping rules. Ask which decision takes precedence when more than one rule or option applies.',
    'Look for an uncovered input or a change of state. Ask what result the owner wants in that situation.')
INTAKE = ('You are an independent policy reviewer. Work from the PUBLIC request. Existing code can be wrong. '
          'Internally construct two different rules still consistent with the request, and a situation in which they produce different observable outcomes. '
          'Then ask the policy owner directly for their actual rule in ordinary Korean. Ask for a decision the owner can make. '
          'Do not ask how code works or if an engineer can implement something. Do not state your guesses as policy. '
          'If nothing is missing, set needed to false. Use a short, verbatim source substring as quote.')
SCHEMA = obj({'needed': base.BOOL, 'quote': base.TEXT, 'possible_rule_1': base.TEXT, 'possible_rule_2': base.TEXT,
              'distinguishing_situation': base.TEXT, 'owner_question': base.TEXT})


def inspect(project, draft, seed, ask):
    current = {p: revision_view(p, code, project['files'][p]) for p, code in draft.items()}
    packet = {'draft_implementation': current, 'public_request': project['brief']}
    records, groups = [], {}
    for index, (role, lens) in enumerate(zip(base.SLOTS, LENSES)):
        key, doc = ask(role, INTAKE + ' ' + lens, packet, SCHEMA, seed+1+index, base.REVIEW_LIMIT)
        records.append({'role': role, 'call': key, 'analysis': doc})
        if doc is None or not doc['needed'] or not doc['owner_question'].strip():
            continue
        question = doc['owner_question'].strip()
        group = groups.setdefault(base.text_key(question), {'question': question, 'proposed_by': []})
        group['proposed_by'].append(role)
    return {'reviews': records, 'questions': list(groups.values())[:base.QUESTION_LIMIT],
            'calls': [r['call'] for r in records], 'invalid': any(r['analysis'] is None for r in records)}
