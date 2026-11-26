"""Compile model-selected, source-cited decision rows to a pure Python function body."""
import ast
import operator
import re
from decimal import Decimal

from backend.structured_output import array, obj


UNITS = {
    'seconds':('time',1,('초','second','seconds','sec','s')),
    'minutes':('time',60,('분','minute','minutes','min')),
    'hours':('time',3600,('시간','hour','hours','hr')),
    'days':('time',86400,('일','day','days')),
    'ms':('time',Decimal('0.001'),('밀리초','millisecond','milliseconds','ms')),
    'bytes':('storage',1,('바이트','byte','bytes','B')),
    'kib':('storage',1024,('KiB','키비바이트')),
    'mib':('storage',1048576,('MiB','메비바이트')),
    'meters':('length',1,('미터','meter','meters')),
    'cm':('length',Decimal('0.01'),('센티미터','centimeter','centimeters','cm')),
}
ALIASES = {alias:name for name,(_,_,aliases) in UNITS.items() for alias in aliases}
MEASURE = re.compile(r'(?<![\w.])([0-9]+(?:\.[0-9]+)?)\s*('+'|'.join(re.escape(k) for k in sorted(ALIASES,key=len,reverse=True))
                     +r')(?![A-Za-z])')
LIST = re.compile(r'(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9_-]*)+)')
ILLUSTRATION = re.compile(r'예를\s*들|예시|가령|예\s*[:：]|가정하|미정|for example|e\.g\.|hypothetical|undetermined',re.I)
CALLS = {'len','set','tuple','list','sorted','any','all','next','min','max','sum','str','int','float','bool','abs','round','enumerate','range','frozenset'}
METHODS = {'get','keys','values','items','count','index','strip','lstrip','rstrip','lower','upper','casefold',
           'startswith','endswith','intersection','issubset','isdisjoint'}


def unit_of(parameter):
    suffix=parameter.casefold().rsplit('_',1)[-1]
    return next((name for name,(_,_,aliases) in UNITS.items() if suffix in {a.lower() for a in aliases}),None)


def catalogue(sources, parameters):
    atoms={}
    for key,text in sources.items():
        for i,match in enumerate(MEASURE.finditer(text),1):
            clause=re.split(r'[。！？!?\n;]|(?<!\be)(?<!\bg)\.(?:\s|$)',text[:match.start()])[-1]
            end=re.split(r'[。！？!?\n;]|\.(?:\s|$)',text[match.end():],1)[0]
            if ILLUSTRATION.search(clause+match[0]+end):
                continue
            number,unit=Decimal(match[1]),ALIASES[match[2]]
            for target in sorted({unit_of(p) for p in parameters}-{None}):
                if UNITS[unit][0]!=UNITS[target][0]:
                    continue
                converted=number*UNITS[unit][1]/UNITS[target][1]
                value=int(converted) if converted==converted.to_integral_value() else float(converted)
                atoms[f'Q_{key}_{i}_{target}']=dict(source=key,kind='quantity',quote=match[0],value=value,unit=target,
                    inputs=[p for p in parameters if unit_of(p)==target])
        for i,match in enumerate(LIST.finditer(text),1):
            items=[s.strip() for s in match[0].split(',')]
            if len(items)!=len(set(items)):
                continue
            sentence=re.split(r'[.!?。！？\n]',text[match.end():],maxsplit=1)[0]
            before=re.split(r'[.!?。！？\n]',text[:match.start()])[-1]
            if ILLUSTRATION.search(before+match[0]+sentence):
                continue
            ordered=bool(re.match(r'\s*(?:순서로|순으로|우선순위로|in (?:that|this) order|in order of priority)',sentence,re.I)
                         or re.search(r'(priority order|in descending priority|순서|우선순위)\s*[:：]\s*$',before,re.I))
            atoms[f'L_{key}_{i}']=dict(source=key,kind='ordered' if ordered else 'listed',quote=match[0],value=items)
    return atoms


def program_schema(sources):
    text={'type':'string','maxLength':550}
    refs=array({'type':'string','enum':list(sources)},0,min(8,len(sources)))
    decision={'action':{'type':'string','enum':['return','defer']},'value':text,'sources':refs}
    return obj({'rules':array(obj({'when':text,**decision}),0,12),'otherwise':obj(decision),'complete':{'type':'boolean'}})


def constant_value(node):
    if isinstance(node,ast.Constant) and type(node.value) in (int,float):
        return node.value
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
        n=constant_value(node.operand)
        return None if n is None else -n if isinstance(node.op,ast.USub) else n
    ops={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv}
    if isinstance(node,ast.BinOp) and type(node.op) in ops:
        left,right=constant_value(node.left),constant_value(node.right)
        if left is not None and right is not None:
            if max(abs(left),abs(right))>10**18:
                raise ValueError('수량 표현 범위를 초과함')
            return ops[type(node.op)](left,right)
    return None


def expression(text, refs, sources, atoms, params, notes, value=False):
    if not text.strip():
        raise ValueError('표현식이 비어 있음')
    node=ast.parse(text.strip(),mode='eval').body
    grounded='\n'.join(sources[r] for r in refs)
    local={v.id for v in ast.walk(node) if isinstance(v,ast.Name) and isinstance(v.ctx,ast.Store)}
    allowed=set(params)|set(atoms)|CALLS|local|{'first_present','has_present'}
    if value and isinstance(node,ast.Name) and node.id not in allowed and re.search(r'(?<![A-Za-z0-9_])'+re.escape(node.id)+r'(?![A-Za-z0-9_])',grounded):
        node=ast.Constant(node.id)
    for term in ast.walk(node):
        if isinstance(term,(ast.Lambda,ast.NamedExpr,ast.Await,ast.Yield,ast.YieldFrom)):
            raise ValueError('결정식에서 지원하지 않는 구문')
        if isinstance(term,ast.Attribute) and term.attr not in METHODS:
            raise ValueError('허용된 순수 메서드가 아님')
        if isinstance(term,ast.Call):
            if not ((isinstance(term.func,ast.Name) and term.func.id in CALLS|{'has_present','first_present'})
                    or (isinstance(term.func,ast.Attribute) and term.func.attr in METHODS)):
                raise ValueError('허용된 결정 연산이 아님')
            if isinstance(term.func,ast.Name) and term.func.id=='first_present' and term.args:
                orders=[a['value'] for a in atoms.values() if a['kind']=='ordered' and a['source'] in refs]
                order=term.args[0]
                seq=atoms.get(order.id,{}).get('value') if isinstance(order,ast.Name) else (
                    [v.value for v in order.elts] if isinstance(order,(ast.List,ast.Tuple)) and all(isinstance(v,ast.Constant) for v in order.elts) else None)
                if seq not in orders:
                    raise ValueError('목록의 우선순위를 확정한 원문이 없음')
        if isinstance(term,ast.Name) and term.id not in allowed:
            raise ValueError('입력·근거표에 없는 이름 '+term.id)
        if isinstance(term,ast.Name) and term.id in atoms and atoms[term.id]['source'] not in refs:
            raise ValueError('참조한 값의 출처가 해당 규칙에 없음')
        if isinstance(term,ast.Constant) and isinstance(term.value,str) and term.value and term.value not in grounded:
            raise ValueError('원문에 없는 문자열 결과 또는 분기값')
        if isinstance(term,(ast.Tuple,ast.List)) and all(isinstance(v,ast.Constant) for v in term.elts):
            sequence=[v.value for v in term.elts]
            for atom in atoms.values():
                if atom['kind']=='ordered' and atom['source'] in refs and all(isinstance(v,str) for v in sequence):
                    if len(sequence)==len(atom['value']) and set(sequence)==set(atom['value']) and sequence!=atom['value']:
                        raise ValueError('인용한 순서와 표현식의 순서가 다름')
        if isinstance(term,ast.Compare):
            for left,right in zip([term.left,*term.comparators[:-1]],term.comparators):
                for var, number in [(left,right),(right,left)]:
                    if not isinstance(var,ast.Name) or var.id not in params or not unit_of(var.id):
                        continue
                    if isinstance(number,ast.Name) and number.id in atoms:
                        atom=atoms[number.id]
                        if atom['kind']=='quantity' and (var.id not in atom['inputs'] or notes[atom['source']]['input'] not in ('none',var.id)):
                            raise ValueError('수량의 근거가 가리킨 입력 또는 단위와 다름')
                    scalar=constant_value(number)
                    if scalar is not None and abs(scalar)>1:
                        matches=[a for a in atoms.values() if a['kind']=='quantity' and a['source'] in refs and var.id in a['inputs']
                                 and notes[a['source']]['input'] in ('none',var.id) and a['value']==scalar]
                        if not matches:
                            raise ValueError('그 입력에 연결된 수량으로 확인되지 않는 문턱값')
    class Lower(ast.NodeTransformer):
        def visit_Name(self,n):
            if n.id not in atoms:
                return n
            v=atoms[n.id]['value']
            return ast.Tuple([ast.Constant(x) for x in v],ast.Load()) if isinstance(v,list) else ast.Constant(v)
        def visit_Call(self,n):
            n=self.generic_visit(n)
            if not isinstance(n.func,ast.Name) or n.func.id not in ('first_present','has_present'):
                return n
            if len(n.args)!=2 or n.keywords:
                raise ValueError('순서·포함 연산에 인자 두 개가 필요함')
            order,items=map(ast.unparse,n.args)
            name='_policy_item'
            while name in allowed:
                name+='_'
            template=(f'next(({name} for {name} in ({order}) if {name} in ({items})), None)' if n.func.id=='first_present'
                      else f'any({name} in ({items}) for {name} in ({order}))')
            return ast.parse(template,mode='eval').body
    return ast.unparse(ast.fix_missing_locations(Lower().visit(node)))


def compile_rows(key,region,program,sources,atoms,notes):
    lines,issues=[],[]
    def put(depth,code,refs):
        lines.append({'depth':depth,'code':code,'sources':refs})
    def outcome(row,depth):
        refs=row['sources']
        if row['action']=='defer':
            put(depth,'raise NotImplementedError',refs)
            return
        try:
            if not refs:
                raise ValueError('확정 반환의 근거 누락')
            value=expression(row['value'],refs,sources,atoms,region['parameters'],notes,value=True)
            put(depth,'return '+value,refs)
        except (ValueError,SyntaxError,ArithmeticError,RecursionError) as exc:
            issues.append(str(exc))
            put(depth,'raise NotImplementedError',refs)
    for i,row in enumerate(program['rules']):
        try:
            if not row['sources']:
                raise ValueError('분기 근거 누락')
            condition=expression(row['when'],row['sources'],sources,atoms,region['parameters'],notes)
        except (ValueError,SyntaxError,ArithmeticError,RecursionError) as exc:
            issues.append(f'{i+1}번째 조건 · {exc}')
            put(0,'raise NotImplementedError',[])
            break
        put(0,'if '+condition+':',row['sources'])
        outcome(row,1)
    else:
        outcome(program['otherwise'],0)
    return {'target':key,'lines':lines}, issues
