def fits_print(width_cm, height_cm):
    if any((_policy_item in 0 for _policy_item in [width_cm, height_cm])):
        raise NotImplementedError
    if width_cm < 0 or height_cm < 0:
        return False
    raise NotImplementedError