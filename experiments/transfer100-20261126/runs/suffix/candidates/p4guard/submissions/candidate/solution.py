def file_suffix(name):
    parts = name.rsplit('.', 1) if '.' in name else [name]
    return '' if len(parts) == 1 or parts[-1] == '' else parts[-1]