def triage(tags):
    for tag in tags:
        if tag in ('billing', 'account', 'privacy'):
            return tag
    raise NotImplementedError
