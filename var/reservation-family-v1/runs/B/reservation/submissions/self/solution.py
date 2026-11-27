def allow_cancel(age_seconds, until_start_seconds):
    if until_start_seconds < 0:
        return False
    if until_start_seconds >= 0:
        return True
    return False