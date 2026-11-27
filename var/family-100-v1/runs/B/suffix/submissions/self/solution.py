def file_suffix(name):
    for i, char in enumerate(name):
        if char == '.':
            if i > 0 and i < len(name) - 1:
                return name[i+1:]
            else:
                return ''
    return ''
