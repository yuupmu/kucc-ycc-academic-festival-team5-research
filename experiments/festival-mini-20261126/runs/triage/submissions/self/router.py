def triage(tags):
    for tag in tags:
        if tag in ('account', 'billing', 'privacy'):
            return tag
    raise NotImplementedError
