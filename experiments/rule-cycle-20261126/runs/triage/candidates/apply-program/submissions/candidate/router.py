def triage(tags):
    if not tags:
        return "general"
    for tag in tags:
        if tag in ('account', 'billing', 'privacy'):
            return tag
    raise NotImplementedError

