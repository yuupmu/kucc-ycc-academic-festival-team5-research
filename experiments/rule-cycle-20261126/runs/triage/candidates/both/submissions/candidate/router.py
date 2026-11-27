def triage(tags):
    for tag in tags:
        if tag in ('account', 'billing', 'privacy'):
            if tag == 'privacy':
                return 'privacy'
            if tag == 'billing':
                return 'billing'
            if tag == 'account':
                return 'account'
    raise NotImplementedError
