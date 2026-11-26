"""Apply the owner's actual answer in the main writer, before the existing review."""
from backend import answer_contracts as contracts, scoped_implementation
from experiments import region_cycle


VERSION = 'grounded-owner-answer-v1'
CONTEXT = (' Each question is context for its own reply. A suggestion in a question establishes no policy. '
           'Apply the outcome the owner actually confirmed to the inputs it covers. A detail about a duration '
           'or term alone supplies no return value. Preserve unrelated behavior. If a short answer could '
           'refer to several questions, leave that point open.')


class AnswerWriter:
    def __init__(self, ask, receipts, previous, starter, prior_writer=None):
        self.ask = ask
        self.receipts = receipts
        self.windows, self.answers = contracts.dialogue(receipts)
        scopes = scoped_implementation.targets(previous, starter)
        self.unique_scope = len({s['path'] for s in scopes.values()}) == 1 and sum(s['kind'] == 'body' for s in scopes.values()) == 1
        self.short_replies = any(contracts.SHORT.fullmatch(s) for s in self.answers.values())
        self.records = []
        usable = prior_writer and prior_writer.get('format') == 'regions' and not prior_writer['error'] and prior_writer['files'] == previous
        self.prior = {r['scope']: r for r in prior_writer['answer_application'] if r['mode'] == 'regions'} if usable else {}

    def contextualize(self, system, packet):
        return system + CONTEXT, {**packet, 'owner_dialogue': [
            dict(questions=w['questions'], replies=[self.answers[rid] for rid in w['answers']]) for w in self.windows]}

    def __call__(self, role, system, packet, schema, seed, limit):
        if role in ('main-rule-plan', 'main-region-decisions') and self.answers and (self.short_replies or not self.unique_scope):
            system, packet = self.contextualize(system, packet)
        key, choice = self.ask(role, system, packet, schema, seed, limit)
        if role == 'main-region-decisions' and self.answers and choice and choice['applicable']:
            choice, record = contracts.bind(choice, packet, self.receipts, self.unique_scope, self.prior.get(packet['함수']))
            self.records.append(dict(mode='regions', scope=packet['함수'], **record))
        return key, choice

    def text(self, role, system, packet, seed, limit):
        if role == 'main-author' and self.answers:
            system, packet = self.contextualize(system, packet)
            self.records.append(dict(mode='native', scope=packet['editable_scope']['name'], issues=[]))
        return self.ask.text(role, system, packet, seed, limit)


def revise(project, previous, receipts, seed, role, ask, prior_writer=None):
    writer = AnswerWriter(ask, receipts, previous, project['files'], prior_writer)
    reply = '\n'.join(r['text'] for r in receipts) or None
    result = region_cycle.revise(project, previous, reply, seed, role, writer)
    result['writer']['answer_application'] = writer.records
    if any(r['issues'] for r in writer.records):
        result['writer']['complete'] = False
        if result['status'] == 'reviewed_complete':
            result['status'] = 'open_limit'
    return result
