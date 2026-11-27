def fits_print(width_cm: int, height_cm: int) -> bool:
    # 음수 확인
    if width_cm < 0 or height_cm < 0:
        return False
    
    # 0 처리: H1/H2에 따라 0은 길이 없음으로 거부
    if width_cm == 0 or height_cm == 0:
        return False
    
    # 상한 확인: P2에 따라 양수이고 상한보다 작아야 함.
    # P3는 상한값이 인쇄 담당자에게 확인 필요라고 함.
    # 현재 정보로는 구체적인 상한값이 없으므로, 
    # '양수인 경우 허용' 로 해석하여 구현합니다.
    # 만약 상한값이 제공된다면: width_cm < MAX_WIDTH and height_cm < MAX_HEIGHT
    # 현재는 MAX_WIDTH = float('inf') 로 간주합니다.
    
    return True