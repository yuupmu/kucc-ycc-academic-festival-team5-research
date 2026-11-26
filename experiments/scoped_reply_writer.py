"""Translate a natural-language owner reply into a scoped edit without running the candidate."""
from backend.allocation_repair import apply_edits, pending_sites
from backend.structured_output import array, obj
from experiments.scoped_transfer import STRING, bound_edits, edit_schema, evidence_choices


PLAN_PROMPT = (
    '공개 명세와 실제 담당자 회신을 함께 읽고, 작성할 함수의 동작을 입력 조건별로 정리하세요. '
    '답변이 적용되는 경우와 그 옆에서 기존 규칙이 계속 적용되는 경우를 모두 포함하세요. '
    '수치 경계라면 경계 미만·같음·초과, 반복 입력이라면 해당 항목과 그 뒤의 다른 항목을 구분하세요. '
    '각 조건에는 함수가 돌려줄 값이나 계속 수행할 동작을 하나씩 적으세요. '
    '원문만으로 결정할 수 없으면 "미정"으로 적으세요. 코드는 쓰지 마세요.'
)
PLAN_SCHEMA = obj({'behavior': array(obj({'when': STRING, 'then': STRING}), 1, 8)})
EDIT_PROMPT = (
    '공개 명세와 담당자 회신을 구현하세요. behavior는 같은 작성자가 정리한 메모이며, '
    '충돌하면 명세와 회신 원문을 따르세요. 수정할 위치로 들어오는 모든 경우에 대해 '
    '메모의 서로 다른 결과를 한 조건식이나 분기로 함께 표현하세요. '
    '참·거짓을 반환할 자리라면 참이 되는 전체 조건을 표현하세요. 반복 중 한 항목의 결정은 '
    '그 뒤 항목의 처리를 보존하세요. 모든 전후 조건이 같은 경우에만 상수 반환이 맞습니다. '
    '예시값을 열거하지 말고 일반 규칙을 구현하세요. 미정인 경로는 보류하고 이미 맞는 코드는 보존하세요. '
    'pending의 키 또는 정확한 원문을 before로 쓰고, after에는 그 위치의 실행문만 쓰세요. '
    'evidence에서 실제 담당자 회신을 선택하세요. 수정할 곳이 없으면 빈 edits를 반환하세요.'
)


def revise(brief, source, history, issues, seed, ask):
    """ask uses the normal recorded-model transport. Only format or source errors enter a retry."""
    choices = evidence_choices(history)
    if not choices:
        raise ValueError('편집하려면 실제 담당자 회신이 필요합니다.')
    calls = []

    def request(role, prompt, packet, schema, call_seed):
        for limit in (1100, 1800):
            key, response = ask(role, prompt, packet, schema, call_seed, limit)
            calls.append(key)
            if response is not None:
                return response
        return None

    public = {'brief': brief, 'dialogue': history}
    plan = request('main-behavior', PLAN_PROMPT, public, PLAN_SCHEMA, seed)
    packet = dict(public, code=source, review=issues, pending=pending_sites(source), evidence=choices)
    if plan is not None:
        packet['behavior'] = plan['behavior']
    fmt = obj({'edits': array(edit_schema(choices), 0, 6)})
    attempts = []
    updated = source
    for retry in range(2):
        proposal = request('main-edit', EDIT_PROMPT, packet, fmt, seed + retry)
        if proposal is None:
            attempts.append({'outcome': 'invalid-output', 'call': calls[-1]})
            break
        try:
            updated = apply_edits(source, bound_edits(proposal, choices), history,
                                  [entry['request_id'] for entry in history])
        except ValueError as exc:
            attempts.append({'outcome': 'rejected', 'call': calls[-1], 'reason': str(exc)})
            packet['edit_format_feedback'] = str(exc)
        else:
            attempts.append({'outcome': 'applied' if updated != source else 'no-edit', 'call': calls[-1]})
            break
    return updated, dict(behavior=plan['behavior'] if plan is not None else None,
                         calls=calls, attempts=attempts)
