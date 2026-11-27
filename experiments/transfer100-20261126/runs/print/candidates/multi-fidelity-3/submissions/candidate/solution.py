def fits_print(width_cm: int, height_cm: int) -> bool:
    if width_cm < 0 and height_cm < 0:
        return False
    if width_cm < 0 and height_cm == 0:
        return False
    if width_cm < 0 and 0 < height_cm < 4:
        return False
    if width_cm < 0 and height_cm == 4:
        return False
    if width_cm < 0 and height_cm > 4:
        return False
    if width_cm == 0 and height_cm < 0:
        return False
    if width_cm == 0 and height_cm == 0:
        return False
    if width_cm == 0 and 0 < height_cm < 4:
        return False
    if width_cm == 0 and height_cm == 4:
        return False
    if width_cm == 0 and height_cm > 4:
        return False
    if 0 < width_cm < 6 and height_cm < 0:
        return False
    if 0 < width_cm < 6 and height_cm == 0:
        return False
    if 0 < width_cm < 6 and 0 < height_cm < 4:
        return True
    if 0 < width_cm < 6 and height_cm == 4:
        return True
    if 0 < width_cm < 6 and height_cm > 4:
        return False
    if width_cm == 6 and height_cm < 0:
        return False
    if width_cm == 6 and height_cm == 0:
        return False
    if width_cm == 6 and 0 < height_cm < 4:
        return True
    if width_cm == 6 and height_cm == 4:
        return True
    if width_cm == 6 and height_cm > 4:
        return False
    if width_cm > 6 and height_cm < 0:
        return False
    if width_cm > 6 and height_cm == 0:
        return False
    if width_cm > 6 and 0 < height_cm < 4:
        return False
    if width_cm > 6 and height_cm == 4:
        return False
    if width_cm > 6 and height_cm > 4:
        return False
    raise NotImplementedError