def triage(tags):
    if not tags:
        raise NotImplementedError
    known = {'account', 'billing', 'privacy'}
    for tag in set(tags):
        if tag in known:
            return tag
    raise NotImplementedError
