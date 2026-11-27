def allow_cancel(age_seconds, until_start_seconds):
    if age_seconds < 0 and until_start_seconds < 0:
        return True
    if age_seconds < 0 and until_start_seconds == 0:
        return True
    if age_seconds < 0 and 0 < until_start_seconds < 86400:
        return True
    if age_seconds < 0 and until_start_seconds == 86400:
        return True
    if age_seconds < 0 and until_start_seconds > 86400:
        return True
    if age_seconds == 0 and until_start_seconds < 0:
        return True
    if age_seconds == 0 and until_start_seconds == 0:
        return True
    if age_seconds == 0 and 0 < until_start_seconds < 86400:
        return True
    if age_seconds == 0 and until_start_seconds == 86400:
        return True
    if age_seconds == 0 and until_start_seconds > 86400:
        return True
    if 0 < age_seconds < 600 and until_start_seconds < 0:
        return True
    if 0 < age_seconds < 600 and until_start_seconds == 0:
        return True
    if 0 < age_seconds < 600 and 0 < until_start_seconds < 86400:
        return True
    if 0 < age_seconds < 600 and until_start_seconds == 86400:
        return True
    if 0 < age_seconds < 600 and until_start_seconds > 86400:
        return True
    if age_seconds == 600 and until_start_seconds < 0:
        return True
    if age_seconds == 600 and until_start_seconds == 0:
        return True
    if age_seconds == 600 and 0 < until_start_seconds < 86400:
        return True
    if age_seconds == 600 and until_start_seconds == 86400:
        return True
    if age_seconds == 600 and until_start_seconds > 86400:
        return True
    if age_seconds > 600 and until_start_seconds < 0:
        return True
    if age_seconds > 600 and until_start_seconds == 0:
        return True
    if age_seconds > 600 and 0 < until_start_seconds < 86400:
        return True
    if age_seconds > 600 and until_start_seconds == 86400:
        return True
    if age_seconds > 600 and until_start_seconds > 86400:
        return False
    raise NotImplementedError