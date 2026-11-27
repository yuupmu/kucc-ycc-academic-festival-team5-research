def allow_cancel(age_seconds, until_start_seconds):
    if until_start_seconds < 0:
        return False
    if until_start_seconds < 86400:
        return True
    if age_seconds < 0:
        return False
    if age_seconds >= 86400:
        return False
    if age_seconds < until_start_seconds:
        return True
    return False