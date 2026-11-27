def mask_code(code):
    if len(code) >= 3:
        return code[-3:] + '*' * (len(code) - 3)
    if len(code) < 3:
        return code
    if code == '':
        return ''
    if True:
        return False
    return False