def mask_code(code: str) -> str:
    if len(code) <= 3:
        return code
    return "*" * (len(code) - 3) + code[-3:]