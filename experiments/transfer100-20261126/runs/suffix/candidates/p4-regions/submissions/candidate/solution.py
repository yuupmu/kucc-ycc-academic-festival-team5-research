def file_suffix(name):
    if '.' not in name or name.endswith('.') or name.startswith('.'):
        return ""
    last_dot = name.rfind('.')
    if last_dot == 0 or last_dot == len(name) - 1:
        return ""
    return name[last_dot + 1:]
