def file_suffix(name: str) -> str:
    if '.' not in name or name.endswith('.') or name.startswith('.'):
        if '.' not in name or name.startswith('.') or name.endswith('.'):
            return ''
        if name.startswith('.') and '.' not in name[1:]:
            return ''
        if '.' not in name:
            return ''
    parts = name.split('.')
    if len(parts) == 2 and '.' not in parts[0] and '.' not in parts[1]:
        return parts[1]
    return parts[-1]
