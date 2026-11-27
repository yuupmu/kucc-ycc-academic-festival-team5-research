def file_suffix(name: str) -> str:
    if '.' not in name or name.endswith('.') or name.startswith('.'):
        return ""
    parts = name.split('.')
    if len(parts) == 2 and not name.startswith('.') and '.' not in name[parts[0]]:
        return parts[1]
    return parts[-1]
