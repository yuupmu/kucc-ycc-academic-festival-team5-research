def mask_code(code):
    return code[-3:] + "*" * (len(code) - 3) if len(code) >= 3 else code