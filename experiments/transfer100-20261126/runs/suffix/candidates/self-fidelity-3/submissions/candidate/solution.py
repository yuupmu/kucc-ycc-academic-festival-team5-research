def file_suffix(name: str) -> str:
    if '.' not in name:
        return ''
    parts = name.split('.')
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[1]
    return parts[-1]
