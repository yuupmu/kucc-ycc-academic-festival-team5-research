"""The main author's two fixed steps: extract authorized decisions, then edit their executable scope."""
from backend import scoped_implementation as edits
from backend.structured_output import array, obj
from experiments import festival_protocol as base
from experiments.festival_refinement import revision_view


PLAN = ('You are the main programmer planning a revision. For each verbatim source, write separately what it establishes and '
        'what it still leaves open. A missing detail never erases a confirmed one. Select the actual input that the established fact governs. '
        'Preserve any stated number, units, equality, precedence or invariant. A request for clarification supplies no new decision. '
        'Use empty strings where nothing is established or nothing remains open. Keep notes short. Select the smallest editable scopes.')
WRITE = ('Write executable code, in one ordinary fenced code block. You are the main programmer. '
         'Implement every decision actually given in the public request and exact owner replies. Source wording overrides preliminary notes '
         'and the previous implementation. Compare early returns and overlapping rules. Preserve confirmed behavior wherever it applies. '
         'When different policies consistent with the sources would produce different outputs for an input, explicitly leave just that case undecided. '
         'Do not invent a default, a threshold or a priority. For a function scope return exactly one definition with the same name and arguments. '
         'Place any needed imports inside the definition. Use native indentation. On an operative Python line you may cite source IDs as a trailing '
         'comment of the form # [P1, H1] using only the actual IDs present. Produce short code. Omit explanations, docstrings and tests.')


def evidence(brief, reply_text):
    sources = base.core.sources(brief, [])
    distinct = dict.fromkeys(s.strip() for s in (reply_text or '').splitlines() if s.strip())
    sources.update({f'H{i}':text for i,text in enumerate(distinct,1)})
    return sources


def write(project, previous, reply_text, seed, ask):
    sources = evidence(project['brief'],reply_text)
    regions = edits.targets(previous,project['files'])
    public_regions = {key:{k:r[k] for k in ('path','name','parameters','kind','signature')} for key,r in regions.items()}
    params = list(dict.fromkeys(p for r in regions.values() for p in r['parameters']))
    detail = obj({'established':base.TEXT, 'input':{'type':'string','enum':['none',*[p for p in params if p!='none']]},
                  'still_open':base.TEXT})
    source_schema = obj({'scopes':array({'type':'string','enum':list(regions)},1,min(16,len(regions))),
                         'notes':obj({k:detail for k in sources})})
    aliases = {path:revision_view(path, code, project['files'][path]) for path,code in previous.items()}
    packet = {'editable_scopes':public_regions, 'public_and_owner_sources':sources}
    k1, intent = ask('main-rule-plan',PLAN,packet,source_schema,seed+600,2000)
    result = dict(calls=[k1], decisions={}, proposed=[], files=previous, bindings={}, error=None, complete=False)
    if intent is None:
        result['error'] = 'invalid_model_output'
        return result
    plan = {k:{**note,'status':'rule' if note['established'].strip() else 'undetermined'} for k,note in intent['notes'].items()}
    result['decisions'] = plan
    scopes = list(dict.fromkeys(intent['scopes']))
    # A request for a whole file subsumes all named body edits in that file.
    whole = {regions[k]['path'] for k in scopes if regions[k]['kind']=='file'}
    scopes = [k for k in scopes if regions[k]['kind']=='file' or regions[k]['path'] not in whole]
    errors = []
    for i, key in enumerate(scopes):
        region = regions[key]
        payload = {'editable_scope':public_regions[key], 'previous_implementation':aliases,
                   'public_request':project['brief'], 'current_owner_replies':[v for k,v in sources.items() if k.startswith('H')],
                   'sources':sources, 'my_preliminary_notes':intent['notes']}
        call, body = ask.text('main-author',WRITE,payload,seed+1000+i,base.AUTHOR_LIMIT)
        result['calls'].append(call)
        try:
            result['proposed'].append(edits.natural_edit(key,region,body,sources))
        except (ValueError,SyntaxError,RecursionError) as exc:
            errors.append(str(exc))
    if errors:
        result['error'] = '; '.join(errors)
        return result
    try:
        files, receipts = edits.apply(previous,regions,result['proposed'],plan)
    except (ValueError,SyntaxError,RecursionError) as exc:
        result['error'] = str(exc)
        return result
    result.update(files=files,bindings=receipts,complete=all(
        not r['still_open'].strip() and r['status']=='rule' and receipts[k]['structural_support'] for k,r in plan.items()))
    return result
