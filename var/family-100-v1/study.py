"""Local ten-condition comparison. Author and reviewer inputs exclude official cases."""
import hashlib,json,os,shutil,sys,time
from pathlib import Path
root=Path(__file__).resolve().parent
sys.path.insert(0,str(root.parents[1]))
from experiments import scoped_transfer as pipeline
from experiments.local_transport import read,save
from experiments.project_review import freeze
MODELS={k:'var/local-models/'+name+'-Q4_K_M.gguf' for k,name in zip('ABC',('Qwen3.5-4B','google_gemma-3-4b-it','microsoft_Phi-4-mini-instruct'))}
TASKS=('title','suffix','mask','upload','print')
GROUPS=('A','B','C','mixed')
PORTS={m:18841+i for i,m in enumerate(MODELS.values())}
KEYS=('solo','self','abc')
CARDS={
 'title':{'s':'연속된 내부 공백은 한 칸으로 줄입니다.','h':'하이픈은 위치와 개수를 그대로 유지합니다.','e':'양끝 공백을 제거한 결과가 빈 문자열이면 untitled를 반환합니다.','p':'양끝 공백을 제거하고 영문자는 소문자로 바꿉니다. 숫자와 한 칸인 단어 사이 공백은 유지합니다.','i':'입력은 영문, 숫자, 하이픈, ASCII 공백으로 된 문자열입니다. 길이 제한은 없습니다.'},
 'suffix':{'m':'점이 여러 개인 보통 파일은 마지막 점 뒤의 부분만 확장자로 사용합니다.','c':'반환하는 확장자는 소문자로 통일합니다.','h':'점으로 시작하고 뒤에 다른 점이 없는 이름은 확장자가 없으므로 빈 문자열을 반환합니다.','x':'점으로 시작해도 뒤에 다른 점이 있으면 마지막 점 뒤의 부분을 사용합니다.','n':'점이 없는 이름은 빈 문자열을 반환합니다.','t':'마지막 글자가 점이면 빈 문자열을 반환합니다.','p':'가운데 점이 하나인 보통 파일은 점 뒤의 부분을 반환하고 점은 붙이지 않습니다.','i':'파일 이름에는 경로 구분자, 공백, 빈 이름이 들어오지 않습니다.'},
 'mask':{'d':'공개하는 쪽은 오른쪽 끝입니다.','k':'공개하는 길이는 세 글자입니다.','s':'길이가 세 글자 이하이면 전부 가립니다.','e':'빈 코드는 빈 문자열을 반환합니다.','p':'가리는 글자마다 별표 하나를 쓰고 결과 길이, 공개 글자의 대소문자와 순서를 유지합니다.','i':'입력에는 영문 대소문자와 숫자만 포함되며 빈 문자열도 가능합니다.'},
 'upload':{'l':'상한은 16바이트입니다.','b':'정확히 상한이면 허용합니다.','z':'0바이트 빈 파일은 거부합니다.','p':'양수 파일은 상한 미만이면 허용하고 초과하면 거부합니다. 음수 크기는 거부합니다.','i':'입력은 정수 바이트 수입니다.'},
 'print':{'w':'가로의 상한은 6센티미터입니다.','h':'세로의 상한은 4센티미터입니다.','b':'각각 자기 상한과 정확히 같아도 허용합니다.','z':'가로나 세로 중 하나라도 0이면 거부합니다.','p':'음수 길이는 거부합니다. 축을 교환하지 않으며 양수는 각 상한보다 작으면 허용하고 하나라도 초과하면 거부합니다.','i':'입력은 정수 센티미터입니다.'}}
PUBLIC={'p','i'}
def key(t,q):
    return hashlib.sha256((t+'\n'+q).encode()).hexdigest()[:18]
def reply(t,codes):
    selected=dict((k,v) for k,v in CARDS[t].items() if k in codes)
    if t=='print' and {'w','h'}<=set(selected):
        selected['w']='가로는 최대 6센티미터, 세로는 최대 4센티미터입니다.';selected.pop('h')
    if t=='mask' and {'d','k'}<=set(selected):
        selected['d']='마지막 세 글자를 공개하고 그 앞은 별표로 가립니다.'; selected.pop('k')
    if not selected:return '질문한 상황에는 추가로 정해진 정책이 없습니다. 결과가 달라지는 입력 조건을 특정해 주세요.'
    return ' '.join(selected.values())
def pending():
    labels=read(root/'labels.json')
    unknown={}
    for d in sorted(root.glob('runs/*/*')):
        t=d.name
        for f in sorted(d.glob('*-questions.json')):
            questions=read(f); entries=[key(t,q) for q in questions]
            if not questions:continue
            for k,q in zip(entries,questions):
                if k not in labels:unknown[k]=(t,q)
            if any(k not in labels for k in entries):continue
            codes={c for k in entries for c in labels[k]}
            assert codes<=set(CARDS[t])
            freeze(f.with_name(f.name.replace('questions','reply')),reply(t,codes))
    return unknown

def run():
    catalog={'models':MODELS,'tasks':TASKS,'rounds':3,'max_questions_per_round':3,'seed':263,
             'groups':['each main solo, self, own-model A/B/C watchers','A main plus one reviewer per family'],
             'assignment':'same A/B/C role prompts. Mixed family at slot j = (task index + round index + j) mod 3, indices start at zero.',
             'draft_failure':'same public scaffold if first implementation cannot be decoded or compiled',
             'oracle':'human proxy assigns canonical policy cards to question text only. Same set receives same natural-language answer.',
             'no_final_repair':'measure three review rounds identically for every reviewer group','grading':'only after every submission is sealed'}
    freeze(root/'design.json',{**catalog,'tasks':list(TASKS)})
    freeze(root/'cards.json',CARDS)
    if not (root/'labels.json').exists():save(root/'labels.json',{})
    bank=root/'calls';bank.mkdir(exist_ok=True)
    for task in TASKS:
        for f in (root.parent/'scoped-100-v1'/task/'calls').glob('*.json'):
            target=bank/f.name
            if not target.exists():os.link(f,target)
    while True:
        pending();finished={}
        for g in GROUPS:
            for i,t in enumerate(TASKS):
                d=root/'runs'/g/t;d.mkdir(exist_ok=True,parents=True)
                if not (d/'calls').exists():(d/'calls').symlink_to(bank,target_is_directory=True)
                if (d/'sealed.json').exists():finished[g+'/'+t]=read(d/'sealed.json');continue
                pending()
                if any(read(f) and not f.with_name(f.name.replace('questions','reply')).exists() for f in d.glob('*-questions.json')):continue
                main=MODELS[g if g!='mixed' else 'A']
                schedule=[[MODELS['ABC'[(i+n+j)%3]] for j in range(3)] for n in range(3)] if g=='mixed' else [[main]*3 for _ in range(3)]
                print('Run',g,t,flush=True)
                pipeline.run(t,d,PORTS[main],model=main,arms=('abc',) if g=='mixed' else ('self','abc'),
                             reviewer_schedule=schedule,model_ports=PORTS,draft_fallback=True)
        if len(finished)==len(GROUPS)*len(TASKS):
            for t in TASKS:assert finished['A/'+t]['solo']==finished['mixed/'+t]['solo']
            freeze(root/'sealed-all.json',finished);print('Sealed all 50 submissions',flush=True);return
        time.sleep(.5)
if __name__=='__main__':run()
