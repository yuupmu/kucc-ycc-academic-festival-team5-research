def large_cover(focus: bool, save_data: bool) -> bool:
    """
    전시 안내 앱에서 큰 표지를 쓸지 정하는 함수입니다.
    
    논리:
    - 집중 보기 신호 (focus=True) 가 들어오면 큰 표지를 사용합니다.
    - 데이터 절약 신호 (save_data=True) 가 들어오면 작은 표지를 사용합니다.
    - 두 신호가 동시에 들어오는 경우, 우선순위를 정해야 합니다.
      문제 설명에 따르면 "집중 보기 신호만"과 "데이터 절약 신호만"이라는 표현이 사용되었으므로,
      두 신호가 동시에 True 인 경우를 명시적으로 다루지 않았습니다.
      일반적인 소프트웨어 설계 관행에 따라, 사용자 경험 (UX) 을 위한 집중 보기 (focus) 가
      데이터 절약 (save_data) 보다 우선시되는 경우가 많습니다.
      따라서 focus=True 일 경우 큰 표지 (True) 를 반환하고, 그렇지 않으면 save_data=True
      일 경우 작은 표지 (False) 를 반환하며, 둘 다 False 라면 작은 표지 (False) 를 반환합니다.
      
    인자:
    focus (bool): 집중 보기 신호 여부. True 라면 큰 표지 사용 신호.
    save_data (bool): 데이터 절약 신호 여부. True 라면 작은 표지 사용 신호.
    
    반환:
    bool: True 인 경우 큰 표지 사용, False 인 경우 작은 표지 사용.
    """
    
    # 집중 보기 신호가 우선시됨 (문제 설명에 따른 논리적 추론)
    if focus:
        return True
    
    # 집중 보기 신호가 없으면 데이터 절약 신호에 따라 결정
    if save_data:
        return False
    
    # 두 신호 모두 False 인 경우 (데이터 절약 필요 없음, 집중 필요 없음)
    # 기본 동작은 작은 표지 사용 (데이터 절약이 없으므로)
    return False
