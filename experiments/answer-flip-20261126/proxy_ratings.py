"""Two fresh local readers. Each call sees one anonymous prompt, brief, dialogue, and input."""
from pathlib import Path
import hashlib,json,os,random,sys
OUT=Path(__file__).resolve().parent
LAB=OUT.parents[1]
sys.path.insert(0,str(LAB))
from experiments.festival_protocol import call_model
from experiments.local_transport import read,local_server,locked_output
from experiments.project_review import freeze
from backend.structured_output import obj
from run_pairs import content_hash

SPECS={'A':('B',16363),'B':('C',94211)}
DIR=OUT/'proxy-ratings'
SYS='당신은 독립적으로 운영 정책의 의미를 읽는 평가자입니다. 입력 인자에 대한 반환값이 공개 명세 또는 실제 담당자 답변으로 확정되는지 판정하세요. 질문자의 추측은 정책이 아닙니다. 필요한 근거가 충분할 때만 known, 아니면 unknown을 고르세요. known이면 value_json에 반환값을 올바른 JSON 값으로 적으세요. unknown이면 value_json은 비우고 어떤 선택이 열려 있는지 reason에 쓰세요. quote에는 결정의 근거 또는 애매한 부분을 보여 주는 공개 명세나 담당자 답변의 한 구절을 정확히 인용하세요. 대화에 묻지 않은 정책을 담당자가 알려 주었는지를 scope로 판정하세요. over라고 판단하면 excess_quote에 바로 그 담당자 구절을 인용하세요. 문장은 간결하게 작성하세요.'
F={'type':'string'}
def enum(*choices):return {'type':'string','enum':list(choices)}
SCHEMA=obj(dict(decision=enum('known','unknown'),value_json=F,quote=F,reason=F,scope=enum('within','over','unclear'),excess_quote=F))

def main():
    os.chdir(LAB);DIR.mkdir(exist_ok=True)
    cards=read(OUT/'blind/inputs.json')
    weights=read(LAB/'var/family-100-v1/weights.json')
    design={r:dict(weight=weights[m],shuffle=s) for r,(m,s) in SPECS.items()}
    freeze(DIR/'design.json',dict(model_readers=design,inputs=content_hash(OUT/'blind/inputs.json'),source=content_hash(Path(__file__)),
        generation_seed=937,limit=[700,1100],task='independent AI proxy, each run gets a fresh single case, no codes or labels'))
    seals={}
    with locked_output(DIR):
        for idx,(r,(m,order_seed)) in enumerate(SPECS.items()):
            model='var/local-models/'+weights[m]['filename'];port=18938+idx
            assert content_hash(LAB/model)==weights[m]['sha256']
            order=list(range(len(cards)));random.Random(order_seed).shuffle(order)
            with local_server(port,model):
                for slot,i in enumerate(order,1):
                    dest=DIR/r/f'{slot:02}';dest.mkdir(parents=True,exist_ok=True)
                    packet=cards[i]
                    calls=[]
                    for limit in (700,1100):
                        key,val=call_model(dest,{'model':model},'독립 정책 평가자',SYS,packet,SCHEMA,937,limit,port)
                        calls.append(key)
                        if val is not None:break
                    freeze(dest/'rating.json',dict(response=val,calls=calls))
                    seals[f'{r}/{slot:02}']=content_hash(dest/'rating.json')
                    print('sealed rating',r,slot,flush=True)
    freeze(DIR/'sealed.json',dict(design=content_hash(DIR/'design.json'),responses=seals))
if __name__=='__main__':main()

