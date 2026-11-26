"""Apply only owner-supported changes to the previously reviewed implementation."""
import ast
import itertools
import math
import re

from backend import answer_contracts, decision_regions, project_syntax, review_contracts, review_literals
from experiments import festival_protocol as base, rule_program_cycle


VERSION = 'review-scoped-owner-patch-v2'


def reported_issues(reviews):
    issues = []
    for review in reviews:
        response = review.get('response') or {}
        if not response.get('needs_code_fix'):
            continue
        for detail in response.get('questions', []):
            if isinstance(detail, str):
                detail = {'question': detail}
            issues.append({'reviewer': review['role'], 'situation': detail.get('situation', ''),
                           'question': detail.get('question', '')})
        if not response.get('questions'):
            issues.append({'reviewer': review['role'], 'situation': '', 'question': ''})
    return issues


def merge_findings(*groups):
    ordered = {}
    for group in groups:
        for issue in group:
            key = (issue['reviewer'], issue['situation'], issue['question'])
            ordered.setdefault(key, issue)
    return list(ordered.values())


def previous_layout(source,target):
    """Recover numeric cut points, never return values, from the reviewed function."""
    arguments=target['parameters']
    if not arguments or len(arguments)>3 or not all(decision_regions.unit_of(name) for name in arguments):
        return None
    fn=next((n for n in ast.walk(ast.parse(source)) if isinstance(n,ast.FunctionDef)
             and n.name==target['name'].split('.')[-1] and n.end_lineno==target['end']),None)
    if fn is None:
        return None
    cuts={arg:set() for arg in arguments}
    for node in ast.walk(fn):
        if not isinstance(node,ast.If):
            continue
        for comparison in ast.walk(node.test):
            if not isinstance(comparison,ast.Compare):
                continue
            terms=[comparison.left,*comparison.comparators]
            for lhs,rhs in zip(terms,terms[1:]):
                for arg,number in [(lhs,rhs),(rhs,lhs)]:
                    if isinstance(arg,ast.Name) and arg.id in cuts and isinstance(number,ast.Constant) and type(number.value) is int:
                        cuts[arg.id].add(number.value)
    if not all(cuts.values()) or math.prod(2*len(v)+1 for v in cuts.values())>64:
        return None
    axes=[]
    for arg in arguments:
        values=sorted(cuts[arg])
        bands=[f'{arg} < {values[0]}']
        for i,v in enumerate(values):
            bands.append(f'{arg} == {v}')
            if i+1<len(values):
                bands.append(f'{v} < {arg} < {values[i+1]}')
        bands.append(f'{arg} > {values[-1]}')
        axes.append(bands)
    cells={' and '.join(parts):{'condition':' and '.join(parts),'anchors':[]} for parts in itertools.product(*axes)}
    return cells,{'True':('True',[]),'False':('False',[]),'defer':(None,[])},'numeric'


COMPARISON = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\s*(==|<=|>=|<|>|=)\s*(-?\d+(?:\.\d+)?)(?![\w.])')
REVERSED = re.compile(r'(?<![\w.])(-?\d+(?:\.\d+)?)\s*(==|<=|>=|<|>|=)\s*([A-Za-z_]\w*)(?![\w.])')
QUALIFIED = re.compile(r'아니면|또는|혹은|제외|빼고|한정|경우에만|(?:인|일) 때만|\b(?:or|unless|except|excluding|but|only if)\b', re.I)


def located_cells(issue, axes, cells, packet=None):
    """Use explicit reviewer coordinates only for location, never as authority for a result."""
    description = issue.get('situation') or issue.get('question', '')
    if description.strip() in cells:
        return {description.strip()}
    literal=review_literals.locate(description,cells)
    if literal or (literal is not None and not axes):
        return literal
    if QUALIFIED.search(description):
        return set()
    bounds = COMPARISON.findall(description)
    inverse={'<':'>','>':'<','<=':'>=','>=':'<=','==':'==','=':'=='}
    bounds.extend((name,inverse[op],value) for value,op,name in REVERSED.findall(description))
    if not bounds:
        return review_contracts.locate(description,packet) if packet else None
    if re.search(r'!=|≠',description):
        return set()
    if not axes:
        # A non-numeric literal layout may name its scalar equality as the cell itself.
        if len(bounds)==1 and bounds[0][1] in ('=','=='):
            name,_,val=bounds[0]
            return {c for c in cells if c == f'{name} == {val}'}
        return None
    matching = set(cells)
    for name, operator, value in bounds:
        if operator == '=':
            operator = '=='
        allowed = axes.get(name, {}).get(f'{name} {operator} {value}')
        if allowed is None:
            return set()
        matching.intersection_update(allowed)
    return matching


def pure_body(fn, module, inserted):
    """A new early return must not bypass side effects in the original implementation."""
    forbidden=(ast.AsyncFunctionDef,ast.Yield,ast.YieldFrom,ast.Await,ast.With,ast.Try,ast.Global,
               ast.Nonlocal,ast.Delete,ast.AugAssign,ast.Import,ast.ImportFrom,ast.ClassDef,ast.NamedExpr)
    pure_builtins={'len','set','frozenset','tuple','list','next','any','all','min','max','sorted','NotImplementedError',
                   'int','str','bool','type'}
    bound={n.id for n in ast.walk(module) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    bound.update(n.arg for n in ast.walk(module) if isinstance(n,ast.arg))
    bound.update(n.name for n in ast.walk(module) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)))
    bound.update(n.asname or n.name.split('.')[0] for n in ast.walk(module) if isinstance(n,ast.alias))
    generated={n.id for expression in inserted for n in ast.walk(ast.parse(expression,mode='eval')) if isinstance(n,ast.Name)}
    if generated&pure_builtins and ('*' in bound or generated&pure_builtins&bound):
        return False
    for node in ast.walk(fn):
        if isinstance(node,forbidden) or (isinstance(node,ast.FunctionDef) and node is not fn):
            return False
        if isinstance(node,ast.Attribute):
            if node.attr not in ('difference','intersection','issubset','isdisjoint'):
                return False
            if not (isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
                    and node.value.func.id in ('set','frozenset')):
                return False
        if isinstance(node,ast.Subscript) and isinstance(node.ctx,ast.Store):
            return False
        if isinstance(node,ast.Call) and not isinstance(node.func,ast.Attribute):
            if not isinstance(node.func,ast.Name) or node.func.id not in pure_builtins-bound or '*' in bound:
                return False
        if isinstance(node,ast.Raise):
            exception=node.exc.func if isinstance(node.exc,ast.Call) else node.exc
            if not isinstance(exception,ast.Name) or exception.id!='NotImplementedError' or exception.id in bound:
                return False
    return True


def apply_to_body(source, target, layout, selected):
    """Replace a return in a recognized disjoint row, or insert narrow guards above the old fallback."""
    cells, results, _ = layout
    lines = source.splitlines(keepends=True)
    syntax = ast.parse(source)
    functions = [node for node in ast.walk(syntax) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
                 and node.name == target['name'].split('.')[-1] and node.end_lineno == target['end']]
    if len(functions) != 1:
        raise ValueError('지적된 함수 본문을 유일하게 확인할 수 없음')
    fn = functions[0]
    body = fn.body[1:] if ast.get_docstring(fn,clean=False) is not None else fn.body
    expressions=[e for key,decision in selected.items() for e in (cells[key]['condition'],results[decision['result']][0]) if e]
    if not body or not pure_body(fn,syntax,expressions):
        raise ValueError('이 함수에 반환 분기를 안전하게 삽입할 수 없음')
    canonical = {ast.dump(ast.parse(cell['condition'],mode='eval').body): name for name,cell in cells.items()}
    early = {}
    for node in body:
        if not isinstance(node, ast.If) or node.orelse or len(node.body)!=1:
            break
        action=node.body[0]
        if not isinstance(action,ast.Return) or action.value is None or action.lineno<=node.lineno or action.end_lineno!=action.lineno:
            break
        key=canonical.get(ast.dump(node.test))
        if key is None or key in early:
            break
        early[key]=action
    additions=[]
    changed=[]
    newline='\r\n' if '\r\n' in source else '\n'
    start=body[0].lineno-1
    indent=target['prefix']
    for key,decision in selected.items():
        value=results[decision['result']][0]
        if value is None:
            continue
        previous=early.get(key)
        if previous is not None:
            old=previous.value
            if ast.dump(old)==ast.dump(ast.parse(value,mode='eval').body):
                continue
            # AST offsets index the UTF-8 bytes of a physical line.
            raw=lines[old.lineno-1].encode('utf-8')
            lines[old.lineno-1]=(raw[:old.col_offset]+value.encode('utf-8')+raw[old.end_col_offset:]).decode('utf-8')
        else:
            additions.extend((f"{indent}if {cells[key]['condition']}:{newline}", f"{indent}{target['unit']}return {value}{newline}"))
        changed.append(key)
    lines[start:start]=additions
    updated=''.join(lines)
    if project_syntax.check(target['path'],updated)=='invalid':
        raise ValueError('수정한 함수의 구문이 잘못됨')
    return updated, changed


def write(project, previous, receipts, seed, ask, reviews, questions, pending_reviews=()):
    issues = merge_findings(reported_issues(reviews), pending_reviews)
    current = receipts[-1] if receipts and questions and list(questions)==receipts[-1]['questions'] else None
    prompts = [dict(reviewer='owner-window', situation='', question=q['question']) for q in (questions if current else [])]
    findings = issues + prompts
    work = dict(files=previous, calls=[], error=None, complete=True, format='review_patch', decisions={},
                bindings={}, regions=[], issues=[], review_findings=issues, answer_application=[],
                unresolved_findings=list(findings))
    if not findings:
        return work
    text='\n'.join(r['text'] for r in receipts)
    def plan(role, system, packet, schema, call_seed, limit):
        packet={**packet,'previous_implementation':previous,'review_findings':issues,
                'owner_dialogue':[{'questions':[q['question'] for q in r['questions']], 'reply':r['text']} for r in receipts]}
        prompt=(system+' Identify only the scopes in the findings or answered questions. Reviewers identify where '
                'to inspect. Only public instructions and actual owner replies establish policy.')
        return ask(role,prompt,packet,schema,call_seed,limit)
    call,intent,sources,targets=rule_program_cycle.same_plan(project,previous,text or None,seed,plan)
    work['calls'].append(call)
    if intent is None:
        work.update(error='invalid_model_output',complete=False)
        return work
    notes=intent['notes']
    work['decisions']={k:{**n,'status':'rule' if n['established'].strip() else 'undetermined'} for k,n in notes.items()}
    body_scopes=[k for k,t in targets.items() if t['kind']=='body']
    functions=[t for t in targets.values() if t['kind']=='body']
    old_words={line.strip() for r in (receipts[:-1] if current else receipts) for line in r['text'].splitlines()}
    fresh_ids={sid for sid,s in sources.items() if sid.startswith('H') and current and s in current['text'].splitlines() and s not in old_words}
    pending=set(range(len(findings)))
    candidate=previous.copy()
    # Applying later source ranges first keeps earlier line numbers stable.
    for scope in sorted(body_scopes,key=lambda k:targets[k]['start'],reverse=True):
        t=targets[scope]
        applicable=[]
        for index,f in enumerate(findings):
            description=f['situation'] or f['question']
            names={name for name,_,_ in COMPARISON.findall(description)}
            names.update(name for _,_,name in REVERSED.findall(description))
            matching=[body for body in functions if names and names<=set(body['parameters'])]
            explicit=[body for body in functions if re.search(r'(?<![\w.])'+re.escape(body['name'])+r'(?![\w.])',description)]
            possible=explicit if explicit else matching
            if (len(functions)==1 and not names) or possible==[t]:
                applicable.append((index,f))
        if not applicable:
            continue
        layout=(review_contracts.grounded_layout(t['parameters'],sources)
                or previous_layout(previous[t['path']],t)
                or decision_regions.layout(t['parameters'],sources,notes))
        resolved=None
        if not layout:
            fallback=review_literals.layout(t['parameters'],sources,receipts)
            if not fallback:
                continue
            layout,resolved=fallback
        cells,results,kind=layout
        packet={'함수':t['name']+'('+t['signature']+')','원문':sources,'입력영역':list(cells),
                '가능한결과':{name:{'동작':value,'근거':refs} for name,(value,refs) in results.items()}}
        if resolved is None:
            resolved=review_contracts.resolve(packet,receipts,[f for _,f in applicable])
        axes=answer_contracts.numeric_axes(cells)
        selected={}
        covered=[]
        for index,f in applicable:
            located=located_cells(f,axes,cells,packet)
            relevant=set()
            for cell,decision in resolved.items():
                if located is not None:
                    eligible=cell in located
                else:
                    eligible=(index>=len(issues) and bool(fresh_ids.intersection(decision['sources'])))
                if eligible:
                    selected[cell]=decision
                    relevant.add(cell)
            if relevant and located is not None and relevant==located:
                covered.append(index)
        if selected:
            try:
                candidate[t['path']],changed=apply_to_body(candidate[t['path']],t,layout,selected)
            except (ValueError,SyntaxError,RecursionError) as exc:
                work['issues'].append(str(exc))
                continue
            pending.difference_update(covered)
            work['answer_application'].append(dict(mode='review_patch',scope=packet['함수'],confirmed=selected,
                                                  changes=changed,issues=[]))
            work['regions'].append(dict(scope=scope,kind=kind,rows=[dict(region=k,selected=d['result'],sources=d['sources'],
                                    implemented=True,issue=None) for k,d in selected.items()]))
    work['unresolved_findings']=[findings[i] for i in sorted(pending)]
    work.update(files=candidate, complete=not (pending or work['issues']))
    return work


def review_code(project, receipts, seed, role, ask, work):
    reply='\n'.join(r['text'] for r in receipts)
    packet={'공개 요구사항':project['brief'],'담당자 답변 원문':[reply] if reply else [],'프로젝트 파일':work['files']}
    reports=[]
    calls=list(work['calls'])
    for i,member in enumerate(('main-self',) if role=='self' else base.SLOTS):
        mode=base.SELF+' '+base.GENERAL+' '+base.CHECK if role=='self' else base.WATCH+' '+base.VIEWS[i]+' '+base.CHECK+base.GROUNDED
        k,response=ask(member,mode,packet,base.review_schema(role=='multi'),seed+1001+i,base.REVIEW_LIMIT)
        calls.append(k)
        reports.append(dict(role=member,response=response))
    ready=work['complete'] and all(r['response'] and not r['response']['questions'] and not r['response']['needs_code_fix'] for r in reports)
    invalid=bool(work['error'] or any(not r['response'] for r in reports))
    status='invalid_output' if invalid else 'reviewed_complete' if ready else 'open_limit'
    return dict(writer=work,reviews=reports,calls=calls,files=work['files'],sha256=base.core.digest(work['files']),status=status)


def revise(project, previous, receipts, seed, role, ask, *, reviews=(), questions=(), prior_writer=None, final_round=False):
    if role not in ('self','multi'):
        raise ValueError('자체 검토 또는 독립 감시를 선택하세요.')
    for r in receipts:
        base.core.natural_reply(r['text'])
    outstanding = [i for i in (prior_writer or {}).get('unresolved_findings', []) if i['reviewer'] != 'owner-window']
    work=write(project,previous,receipts,seed,ask,reviews,questions,outstanding)
    outcome=review_code(project,receipts,seed,role,ask,work)
    if not final_round or outcome['status']=='invalid_output':
        return outcome
    checked={(i['situation'],i['question']) for i in work['review_findings']}
    flagged=reported_issues(outcome['reviews'])
    if not any((i['situation'],i['question']) not in checked for i in flagged):
        return outcome
    # A final post-write finding gets one scoped pass on the existing replies. There
    # is no new owner window. If the code changes, the same reviewers see that revision.
    repair=write(project,outcome['files'],receipts,seed,ask,outcome['reviews'],[])
    work['final_review']=dict(findings=flagged,issues=repair['issues'],unresolved=repair.get('unresolved_findings',[]),
                              error=repair['error'],calls=repair['calls'])
    work['unresolved_findings']=merge_findings(work['unresolved_findings'], repair['unresolved_findings'])
    work['complete']=work['complete'] and repair['complete']
    work['answer_application'].extend(repair['answer_application'])
    work['regions'].extend(repair['regions'])
    work['issues'].extend(repair['issues'])
    outcome['calls'].extend(repair['calls'])
    if repair['error']:
        work['error']=repair['error']
        outcome['status']='invalid_output'
        return outcome
    if repair['files']==outcome['files']:
        return outcome
    original_calls=outcome['calls']
    work['files']=repair['files']
    closed=review_code(project,receipts,seed,role,ask,work)
    closed['calls']=original_calls+closed['calls'][len(work['calls']):]
    return closed

