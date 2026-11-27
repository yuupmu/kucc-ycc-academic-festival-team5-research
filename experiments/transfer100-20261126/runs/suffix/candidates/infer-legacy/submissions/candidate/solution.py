def file_suffix(name):
    if '.' not in name or name.endswith('.'): return ''
    if name.startswith('.') and '.' not in name[1:]: return ''
    return name.split('.')[-1]