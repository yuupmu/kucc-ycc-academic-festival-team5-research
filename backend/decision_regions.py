"""Finite input regions for sourced numeric cutoffs and explicitly order-independent collections."""
import itertools
import math
import re

from backend.anchored_program import catalogue, unit_of
from backend.structured_output import array, obj


def numeric_regions(params,sources,notes,atoms):
    if len(params)>3 or not all(unit_of(p) for p in params):
        return None
    raw='\n'.join(sources.values())
    if not (re.search(r'->\s*bool\b',raw) or ('True' in raw and 'False' in raw)):
        return None
    cuts={p:{} for p in params}
    for atom in atoms.values():
        if atom['kind']!='quantity':
            continue
        target=notes[atom['source']]['input']
        if target not in cuts or target not in atom['inputs']:
            return None
        cuts[target].setdefault(atom['value'],[]).append(atom['source'])
    if not any(cuts.values()):
        return None
    origin=bool(re.search(r'(?<![0-9.])0(?![0-9.])',raw))
    axes=[]
    # Keep interval boundaries separate from their endpoints. A cut organizes inputs; it supplies no outcome.
    for p in params:
        if origin:
            cuts[p].setdefault(0,[])
        values=sorted(cuts[p])
        if not values:
            axes.append([(None,[])])
            continue
        axis=[(f'{p} < {values[0]}',cuts[p][values[0]])]
        for i,v in enumerate(values):
            axis.append((f'{p} == {v}',cuts[p][v]))
            if i+1<len(values):
                nxt=values[i+1]
                axis.append((f'{v} < {p} < {nxt}',cuts[p][v]+cuts[p][nxt]))
        axis.append((f'{p} > {values[-1]}',cuts[p][values[-1]]))
        axes.append(axis)
    if math.prod(map(len,axes))>32:
        return None
    cells={}
    for parts in itertools.product(*axes):
        key=' and '.join(s for s,_ in parts if s) or 'True'
        cells[key]=dict(condition=key,anchors=list(dict.fromkeys(k for _,refs in parts for k in refs)))
    return cells,{'True':('True',[]),'False':('False',[]),'defer':(None,[])},'numeric'


def collection_regions(params,sources,atoms):
    if len(params)!=1:
        return None
    status=' '.join(sources.values())
    invariant=(re.search(r'순서.{0,55}(?:바뀌어도 같|영향을? 받지|무관|상관없)',status) and '중복' in status
               or re.search(r'(?:order|duplicates?).{0,65}(?:irrelevant|do not (?:matter|affect)|do not change|ignored|independent)',status,re.I)
               and re.search(r'order',status,re.I) and re.search(r'duplicat',status,re.I))
    groups=[a for a in atoms.values() if a['kind'] in ('listed','ordered')]
    if not invariant or not groups or len(set(tuple(sorted(a['value'])) for a in groups))!=1:
        return None
    group=groups[0]
    if len(group['value'])>10:
        return None
    p=params[0]
    seq=tuple(group['value'])
    known=f'set({p}).intersection({seq!r})'
    unknown=f'set({p}).difference({seq!r})'
    cells={}
    for description,condition in [('empty input',f'not {p}'),('nonempty, no declared values',f'{p} and not {known}')]:
        cells[description]={'condition':condition,'anchors':[group['source']]}
    for count,test in [('exactly one distinct declared value','== 1'),('several distinct declared values','> 1')]:
        for extras,check in [('only declared values','not '),('also undeclared values','')]:
            cells[f'{count}, {extras}']=dict(condition=f'len({known}) {test} and {check}{unknown}',anchors=[group['source']])
    outputs={'defer':(None,[]),'sole declared value':(f'next(iter({known}))',[group['source']])}
    for a in groups:
        if a['kind']=='ordered':
            key='first present by '+' > '.join(a['value'])
            outputs[key]=(f'next(v for v in {tuple(a["value"])!r} if v in {p})',[a['source']])
    # Return labels must occur in the raw sources. Quoted words and literal terms in mixed-script prose are eligible.
    for k,raw in sources.items():
        labels=re.findall(r'''["'`]([A-Za-z][\w-]{0,40})["'`]''',raw)
        if re.search('[가-힣]',raw):
            labels.extend(re.findall(r'(?<![A-Za-z_])([a-z][A-Za-z_-]*)(?![A-Za-z_])',raw))
        for label in labels:
            if label in params or label in ('def','return') or re.search(r'\b'+re.escape(label)+r'\s*\(',raw):
                continue
            key='literal '+repr(label)
            if key not in outputs:
                outputs[key]=(repr(label),[])
            outputs[key][1].append(k)
    return cells,outputs,'collection'


def layout(params,sources,notes):
    atoms=catalogue(sources,params)
    return numeric_regions(params,sources,notes,atoms) or collection_regions(params,sources,atoms)


def form(cells,outputs,sources):
    decision=obj({'result':{'type':'string','enum':list(outputs)},'sources':array({'type':'string','enum':list(sources)},0,min(len(sources),5))})
    return obj({'applicable':{'type':'boolean'},'regions':obj({name:decision for name in cells})})


def apply_choices(key,layout,choices,sources):
    cells,outputs,kind=layout
    lines,ledger=[],[]
    for name,region in cells.items():
        row=choices[name]
        result=row['result']
        statement,required=outputs[result]
        refs=list(dict.fromkeys(row['sources']))
        issue=None
        if statement is not None and (not refs or not set(refs)<=sources.keys() or (required and not set(required).intersection(refs))):
            issue='반환 결과를 허가하는 원문 인용 누락'
        if kind=='collection' and ((result=='sole declared value' and not name.startswith('exactly one')) or
                (result.startswith('first present by') and not name.startswith(('exactly one','several')))):
            issue='해당 입력 영역에서 반환 연산이 정의되지 않음'
        if issue:
            statement=None
        ledger.append(dict(region=name,selected=result,sources=refs,issue=issue,implemented=statement is not None))
        if statement is None:
            continue
        lines.append(dict(depth=0,code='if '+region['condition']+':',sources=list(dict.fromkeys(region['anchors']+refs))))
        lines.append(dict(depth=1,code='return '+statement,sources=refs))
    lines.append(dict(depth=0,code='raise NotImplementedError',sources=[]))
    return {'target':key,'lines':lines},ledger
