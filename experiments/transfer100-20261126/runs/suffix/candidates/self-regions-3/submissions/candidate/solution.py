def file_suffix(name: str) -> str:
    if name.count('.') != 1:
        return name
    parts = name.split('.')
    if parts[0] == '' or parts[-1] == '':
        return name
    return parts[-1]
