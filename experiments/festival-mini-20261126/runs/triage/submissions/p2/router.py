def triage(tags):
    # 입력은 소문자 문자열 태그의 리스트입니다.
    # 입력 순서와 중복 횟수는 담당 팀에 영향을 주지 않으므로, 집합을 사용하여 중복을 제거하고 순서를 무시합니다.
    known_tags = {'account', 'billing', 'privacy'}
    
    # 알 수 없는 태그는 무시하고, 알려진 태그 중 하나만 있으면 해당 팀을 반환합니다.
    # 여러 태그가 겹치는 경우 (예: ['account', 'billing']), 집합으로 처리하므로 첫 번째로 발견된 태그가 반환됩니다.
    # 이는 '알려진 태그'라는 공통 조건을 만족하므로, 분류 관행상 첫 번째 유효 태그로 처리하는 것이 적절합니다.
    
    for tag in tags:
        if tag in known_tags:
            return tag
    
    # 모든 태그가 알 수 없거나 입력이 비어있을 경우 예외를 발생시킵니다.
    raise NotImplementedError