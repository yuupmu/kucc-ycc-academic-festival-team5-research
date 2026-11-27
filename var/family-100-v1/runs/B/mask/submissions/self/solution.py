def mask_code(code):
    if not code:
        return code

    masked_code = list(code)
    for i in range(len(code)):
        if i % 2 == 0:
            masked_code[i] = '*'
    return ''.join(masked_code)
