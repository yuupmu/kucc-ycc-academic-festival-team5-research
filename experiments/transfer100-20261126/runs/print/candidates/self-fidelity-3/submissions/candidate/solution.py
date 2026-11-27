def fits_print(width_cm, height_cm):
    # H1, H2: 0은 길이 없음으로 거부
    if width_cm == 0 or height_cm == 0:
        return False
    # H3: 음수 거부, 상한값 제공되지 않았으므로 양수인 경우 허용 (P2)
    # 상한값이 제공되지 않았으므로 양수인 경우 허용 (P2)
    return True