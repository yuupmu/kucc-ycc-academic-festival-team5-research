def fits_print(width_cm, height_cm):
    if width_cm <= 0 or height_cm <= 0:
        return False
    if width_cm > 6 or height_cm > 4:
        return False
    if width_cm == height_cm:
        return True
    else:
        return False
