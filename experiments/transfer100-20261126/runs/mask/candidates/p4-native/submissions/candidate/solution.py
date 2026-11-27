def mask_code(code):

    if not code:
        return ""

    if len(code) <= 3:
        return "*" * len(code)

    return "*" * (len(code) - 3) + code[-3:]