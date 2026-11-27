def fits_print(width_cm, height_cm):
    if width_cm <= 0 or height_cm <= 0:
        return False

    max_width_cm = 200  # 예시 값, 실제 값으로 변경 필요
    max_height_cm = 150 # 예시 값, 실제 값으로 변경 필요

    if width_cm > max_width_cm or height_cm > max_height_cm:
        return False

    return True