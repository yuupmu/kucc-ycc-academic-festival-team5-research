def fits_print(width_cm, height_cm):
    if width_cm < 0 or height_cm < 0:
        return False
    if width_cm == 0:
        return False
    if height_cm == 0:
        return False
    if width_cm >= 0 and height_cm >= 0:
        return True
    return False