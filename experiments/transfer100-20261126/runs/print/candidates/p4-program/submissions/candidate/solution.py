def fits_print(width_cm: int, height_cm: int) -> bool:
    # 음수 확인
    if width_cm < 0 or height_cm < 0:
        return False
    
    # 0 처리: 가로/세로 길이 없음이므로 거부
    if width_cm == 0 or height_cm == 0:
        return False
    
    # 상한 확인: 가로 6cm, 세로 4cm. 상한과 같은 길이는 허용 (strictly less than)
    if width_cm >= 6 or height_cm >= 4:
        return False
    
    return True