def mask_code(code: str) -> str:
    if len(code) == 0:
        return code
    if len(code) <= 3:
        return "*" * len(code)
    return code[-3:] + "*" * (len(code) - 3)