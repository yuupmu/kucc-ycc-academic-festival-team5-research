def triage(tags):
    for tag in tags:
        if tag in ('billing', 'account', 'privacy'):
            return 'privacy'
    raise NotImplementedError
