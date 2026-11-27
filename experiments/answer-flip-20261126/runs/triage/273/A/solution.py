def triage(tags):
    for tag in tags:
        if tag in ('privacy', 'billing', 'account'):
            return tag
    raise NotImplementedError
