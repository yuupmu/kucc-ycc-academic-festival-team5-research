def fits_print(width_cm: int, height_cm: int) -> bool:
    # 음수 확인 (P2)
    if width_cm < 0 or height_cm < 0:
        return False
    
    # 0 처리 (H2, H3)
    if width_cm == 0 or height_cm == 0:
        return False
    
    # 상한 확인 (H1: 상한과 같아도 허용, P2: 초과하면 거부)
    # 상한 값이 정의되지 않았으므로 무한대 가정 (P2: 상한보다 작으면 허용)
    # H1에 따라 <= 사용
    if width_cm > float('inf') or height_cm > float('inf'):
        return False
    
    return True