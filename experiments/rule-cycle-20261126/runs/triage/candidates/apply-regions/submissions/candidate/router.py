def triage(tags):
    if not tags:
        return 'general'
    if len(set(tags).intersection(('account', 'billing', 'privacy'))) == 1 and not set(tags).difference(('account', 'billing', 'privacy')):
        return next(iter(set(tags).intersection(('account', 'billing', 'privacy'))))
    if len(set(tags).intersection(('account', 'billing', 'privacy'))) == 1 and set(tags).difference(('account', 'billing', 'privacy')):
        return next(iter(set(tags).intersection(('account', 'billing', 'privacy'))))
    raise NotImplementedError
