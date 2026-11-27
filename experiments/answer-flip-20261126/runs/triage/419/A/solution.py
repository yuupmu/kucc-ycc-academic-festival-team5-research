def triage(tags):
    for tag in tags:
        if tag in ('account', 'billing', 'privacy') and not any(t in ('account', 'billing', 'privacy') for t in tags[:tags.index(tag)]):
            return tag
    raise NotImplementedError
