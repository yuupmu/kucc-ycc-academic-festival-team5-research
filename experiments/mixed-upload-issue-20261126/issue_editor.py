"""An explicitly reviewed exception for a frozen, fully evidenced set of pending sites."""
from backend.project_review import digest
from experiments import guarded_reply, reply_pipeline


FIELDS = ('brief', 'code', 'dialogue', 'review', 'pending', 'evidence')
LOCATION_NOTE = ' review는 감시자가 지적한 코드 위치입니다. 정책의 근거는 공개 명세와 담당자의 실제 회신입니다.'


def authorized(packet, scope):
    if digest({k: packet[k] for k in FIELDS}) != scope['input_digest']:
        return False
    targets = scope['findings']
    if [row['issue'] for row in targets] != packet['review'] or not targets or not all(row['sites'] for row in targets):
        return False
    if {s for row in targets for s in row['sites']} != set(packet['pending']):
        return False
    for rule in scope['checked_evidence']:
        source = packet['brief'] if rule['source'] == 'public' else packet['evidence'][rule['source']]['quote']
        if not rule['quote'] or rule['quote'] not in source:
            return False
    return bool(scope['checked_evidence']) and guarded_reply.scalar_parameter(dict(packet, review=[])) is not None


def with_scope(transport, scope):
    default = reply_pipeline.with_guards(transport)

    def call(out, design, role, prompt, packet, schema, seed, limit, port):
        if role != 'main-edit' or not authorized(packet, scope):
            return default(out, design, role, prompt, packet, schema, seed, limit, port)

        def attach_review(dest, config, inner_role, system, public, fmt, call_seed, cap, endpoint):
            if inner_role == 'main-predicates':
                public = dict(public, code=packet['code'], pending=packet['pending'], review=packet['review'])
                system += LOCATION_NOTE
            return transport(dest, config, inner_role, system, public, fmt, call_seed, cap, endpoint)

        # Scope and human evidence have already been matched. The retained encoder accepts a
        # structurally eligible packet; the actual wire request carries both original reviews.
        return reply_pipeline.with_guards(attach_review)(out, design, role, prompt, dict(packet, review=[]),
                                                          schema, seed, limit, port)
    return call
