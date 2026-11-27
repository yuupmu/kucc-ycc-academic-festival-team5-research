def allow_cancel(age_seconds, until_start_seconds):
    if age_seconds < 0:
        return False
    if age_seconds >= 86400 and until_start_seconds >= 0:
        return False
    return True