def file_suffix(name):
    if (any((_policy_item in name for _policy_item in ['.'])) and (not name.startswith('.')) and (not name.endswith('.')),):
        raise NotImplementedError
    if (not any((_policy_item in name for _policy_item in ['.'])),):
        raise NotImplementedError
    if (name.startswith('.') and (not any((_policy_item in name for _policy_item in ['.', '.']))),):
        raise NotImplementedError
    if (name.startswith('.') and any((_policy_item in name for _policy_item in ['.', '.'])),):
        raise NotImplementedError
    if (name.endswith('.'),):
        raise NotImplementedError
    raise NotImplementedError
