def triage(tags):
    if len(set(tags).intersection(('account', 'billing', 'privacy'))) > 1 and not set(tags).difference(('account', 'billing', 'privacy')):
        return next(v for v in ('privacy', 'billing', 'account') if v in tags)
    for tag in tags:
        if tag in ('account', 'billing', 'privacy'):
            return tag
    raise NotImplementedError
