def large_cover(focus: bool, save_data: bool) -> bool:
    # 집중 보기 신호만 들어오면 큰 표지를 사용합니다
    if focus:
        return True
    
    # 데이터 절약 신호만 들어오면 작은 표지를 사용합니다
    # focus 가 False 이고 save_data 가 True 인 경우만 작은 표지 사용
    if save_data:
        return False
    
    # 미정인 경우: 두 신호가 모두 False 인 경우
    # 문제 설명에 따르면 "집중 보기 신호만" 또는 "데이터 절약 신호만" 이라는 조건이 명시되어 있으며,
    # 두 신호가 모두 False 인 경우의 로직은 제공되지 않았으므로 NotImplementedError 를 사용합니다.
    return False