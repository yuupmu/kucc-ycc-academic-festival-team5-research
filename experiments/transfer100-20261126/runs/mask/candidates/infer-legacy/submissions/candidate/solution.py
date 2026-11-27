def mask_code(code):
    return "*" * len(code) if len(code) <= 3 else "*" * (len(code) - 3) + code[-3:]