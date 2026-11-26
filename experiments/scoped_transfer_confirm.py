"""Blind owner-answer confirmation for a sealed ABC candidate, before official grading."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

from backend.allocation_repair import apply_edits
from backend.isolated import run_cases
from backend.structured_output import array, obj
from experiments.festival_protocol import call_model
from experiments.local_transport import read
from experiments.project_review import freeze, publish
from experiments.scoped_transfer import STRING, bound_edits, edit_schema, evidence_choices

# Only the candidate function receives case arguments. The scorer stays outside its process.
ADAPTER = """
def simulate(initial_state, events):
    return {'value':globals()[initial_state['call']](*initial_state['args'])}
"""


def edit_sites(code, function):
    func = next(n for n in ast.parse(code).body if isinstance(n,ast.FunctionDef) and n.name==function)
    sites = []
    for node in ast.walk(func):
        part = node.test if isinstance(node,ast.If) else node
        if part is node and not isinstance(node,(ast.Return, ast.Assign, ast.Raise)):
            continue
        text = ast.get_source_segment(code,part)
        if code.count(text)==1:
            sites.append(text)
    return sites


def run(out,port):
    design = read(out/'design.json')
    parent = read(out/'sealed.json')
    freeze(out/'confirmation-design.json',dict(parent=parent['abc'], interpretation_seed=702,
         candidate_seeds=[703,704], max_cases=16, fallback='retain original ABC submission'))
    source = (out/'submissions/abc/solution.py').read_text()
    assert hashlib.sha256(source.encode()).hexdigest()==parent['abc']
    history = read(out/'abc-3-snapshot.json')['dialogue']
    if not history:
        raise ValueError('No owner evidence for confirmation')
    calls = read(out/'abc.json')['calls'].copy()
    project = design['project']
    function = ast.parse(project['files']['solution.py']).body[0].name
    packet = dict(brief=project['brief'],answers=[h['answer']['text'] for h in history])
    def call(role,prompt,data,schema,seed):
        key, response = call_model(out,design,role,prompt,data,schema,seed,1500,port)
        calls.append(key)
        if response is None:
            raise ValueError('Invalid model response '+key)
        return response
    probes = call('owner-reader','코드에 접근할 수 없는 독립 검토자입니다. 공개 요구와 담당자 답변에 따라 그 답의 적용과 예외를 구별하는 다양한 입력을 고르세요. 각 답변에 명시된 서로 다른 경계 양쪽과 정확히 경계인 경우, 예외, 조합을 포함하세요. args와 expected는 각각 JSON 배열과 JSON 반환값을 인코딩한 문자열입니다. 확정된 결과만 작성합니다.',
                  packet,obj({'cases':array(obj({'args':STRING,'expected':STRING}),4,16)}),702)['cases']
    payload = [dict(initial_state={'call':function,'args':json.loads(p['args'])},events=[]) for p in probes]
    literals = {'True':'true','False':'false','None':'null'}
    expected = [json.loads(literals.get(p['expected'],p['expected'])) for p in probes]
    def confirmed(code):
        rows = run_cases(code+ADAPTER,payload,'allocation',hash_seed=0)
        return len(rows)==len(expected) and all(not row['error'] and isinstance(row['actual'],dict) and
                    type(row['actual'].get('value')) is type(value) and row['actual']['value']==value
                    for row,value in zip(rows,expected))
    ok = confirmed(source)
    reasons = []
    if not ok:
        sites = edit_sites(source,function)
        choices = evidence_choices(history)
        edit = edit_schema(choices,sites)
        for seed in (703,704):
            response = call('scoped-main','담당자 답변을 실행 코드에 반영하세요. before는 sites에서 실제 수정할 조건식이나 계산문을 고르고 after에는 그 자리에 넣을 코드를 쓰세요. 조건식은 같은 위치에 들어가는 조건식 하나로 대체합니다. 한 조건식에 서로 다른 정책이 적용되면 각 입력 조건에 적합한 판단을 표현하세요. 이미 맞는 분기는 보존하세요. evidence에서 수정의 근거가 되는 담당자 답변을 선택하세요.',
                            dict(brief=packet['brief'],code=source,sites=sites,dialogue=history,evidence=choices),
                            obj({'edits':array(edit,0,5)}),seed)
            edits = bound_edits(response,choices)
            try:
                candidate = apply_edits(source,edits,history,[h['request_id'] for h in history])
            except ValueError as exc:
                reasons.append(str(exc))
                continue
            if confirmed(candidate):
                source,ok=candidate,True
                break
            reasons.append('owner checks unresolved')
    publish(out,'abc-confirmed',{'solution.py':source})
    freeze(out/'abc-confirmed.json',dict(calls=calls,confirmed=ok,probes=probes,diagnostics=reasons))
    freeze(out/'sealed-confirmation.json',{**parent,'abc-confirmed':hashlib.sha256(source.encode()).hexdigest()})
    print('Confirmation arm sealed',ok,len(probes))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('out',type=Path)
    parser.add_argument('--port',type=int,default=18821)
    args=parser.parse_args()
    run(args.out,args.port)
