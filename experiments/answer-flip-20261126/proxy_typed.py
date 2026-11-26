"""Repeat the blind reading using labeled speakers and typed scalar returns; keep the first ratings."""
from pathlib import Path
import json,os,random
from proxy_ratings import OUT,LAB,SPECS,F,enum
from experiments.local_transport import read,local_server,locked_output
from experiments.project_review import freeze
from experiments.festival_protocol import call_model
from backend.structured_output import obj
from run_pairs import content_hash

DIR=OUT/'proxy-typed'
SYS='운영 담당자의 입장에서 입력 하나를 독립적으로 판정하세요. 공개 명세와 실제 담당자 답변만 근거입니다. 질문자의 설명은 담당자 결정이 아닙니다. 답이 정해지면 decision의 status는 known, result에는 실제 함수 반환값을 넣으세요. 미정이면 status만 unknown으로 고르세요. quote에는 명세나 담당자 답의 근거 구절을 그대로 인용하세요. reason에 값 또는 미정인 이유를 간단히 쓰세요. scope는 담당자 회신이 질문받은 범위를 넘어섰는지 뜻합니다. 회신이 전혀 없으면 no_reply, 범위 안이면 within, 넘으면 over, 애매하면 unclear를 고르세요. over라면 excess_quote에 실제 담당자 답의 해당 구절을 적으세요.'
def schema(kind):
    decision={'oneOf':[obj({'status':enum('known'),'result':{'type':kind}}),obj({'status':enum('unknown')})]}
    return obj({'decision':decision,'quote':F,'reason':F,'scope':enum('no_reply','within','over','unclear'),'excess_quote':F})
def main():
    os.chdir(LAB);DIR.mkdir(exist_ok=True)
    cards=read(OUT/'blind/inputs.json')
    weights=read(LAB/'var/family-100-v1/weights.json')
    spec=dict(source=content_hash(Path(__file__)),inputs=content_hash(OUT/'blind/inputs.json'),
           first_seal=content_hash(OUT/'proxy-ratings/sealed.json'),method='Post-hoc measurement check. Identical source data, individual sessions. Add explicit speaker labels and constrain the kind of the return value solely from the public API.')
    freeze(DIR/'design.json',spec)
    seals={}
    with locked_output(DIR):
        for idx,(r,(m,order_seed)) in enumerate(SPECS.items()):
            model='var/local-models/'+weights[m]['filename'];port=18938+idx
            assert content_hash(LAB/model)==weights[m]['sha256']
            order=list(range(len(cards)));random.Random(order_seed).shuffle(order)
            with local_server(port,model):
                for slot,i in enumerate(order,1):
                    d=DIR/r/f'{slot:02}';d.mkdir(exist_ok=True,parents=True);c=cards[i]
                    kind='boolean' if any(x in c['brief'] for x in ('-> bool','True','False')) else 'string'
                    packet={'공개 명세':c['brief'],'실제 문답':[{'담당자에게 보낸 질문':q,'담당자의 실제 답변':a} for q,a in c['dialogue']],
                            '입력 인자 목록':c['args'],'공개 반환 형식':kind}
                    calls=[]
                    for limit in (700,1100):
                        key,value=call_model(d,{'model':model},'독립 정책 평가자',SYS,packet,schema(kind),937,limit,port)
                        calls.append(key)
                        if value is not None:break
                    freeze(d/'rating.json',dict(response=value,calls=calls))
                    seals[f'{r}/{slot:02}']=content_hash(d/'rating.json')
                    print('typed rating',r,slot,flush=True)
    freeze(DIR/'sealed.json',{'design':content_hash(DIR/'design.json'),'responses':seals})
if __name__=='__main__':main()

