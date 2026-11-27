def file_suffix(name: str) -> str:
    if '.' not in name or name.endswith('.') or name.startswith('.') or name.endswith('') or name == '':
        return ""
    parts = name.split('.')
    if len(parts) == 1:
        return ""
    if parts[0] == '':
        return ""
    if len(parts) == 2:
        return parts[1]
    return parts[-1]
