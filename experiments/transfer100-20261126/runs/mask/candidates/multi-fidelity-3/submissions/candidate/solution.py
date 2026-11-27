def mask_code(code: str) -> str:
    if len(code) == 0:
        return ""
    if len(code) <= 3:
        return "*" * len(code)
    return "*" * (len(code) - 3) + code[-3:]