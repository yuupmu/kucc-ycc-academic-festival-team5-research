"""Researcher-owned, pre-registered tasks and 100 independent input rows. Not imported by the model runner."""
from pathlib import Path

from experiments.local_transport import save
from experiments.project_review import freeze

ROOT = Path(__file__).resolve().parent/'transfer100-20261126'

TASKS = {
 'title': dict(name='표시 제목 정리', function='clean_title', parameters='text',
   brief='표시 제목을 정리하는 clean_title(text) -> str 함수를 구현하세요. 입력은 영문 대소문자, 숫자, 하이픈, ASCII 공백으로만 된 문자열입니다. 빈 문자열도 가능합니다.\n양끝 공백은 제거하고 영문자는 소문자로 바꿉니다. 숫자는 그대로 유지합니다. 내부 공백이 하나인 평범한 단어 사이 공백은 유지합니다.\n연속된 내부 공백, 하이픈, 비어 있는 제목을 어떻게 표시할지는 편집 담당자의 기준을 따릅니다. 길이 제한은 없습니다.',
   cards={'spaces':'내부에 공백이 여러 개 연속되어 있으면 공백 하나로 줄입니다.',
          'hyphen':'하이픈은 개수와 위치를 그대로 유지합니다.',
          'empty':'양끝 공백을 제거한 결과가 빈 문자열이면 untitled를 반환합니다.',
          'public':'양끝 공백을 제거하고 영문자는 소문자로 바꾸며, 숫자와 원래 한 칸인 단어 사이 공백은 유지합니다. 길이 제한은 없습니다.'},
   cases=[
    ('공개 기본 변환','public',['Hello'],'hello',[]),('공개 기본 변환','public',['  NEWS  '],'news',[]),
    ('공개 기본 변환','public',['Release 2'],'release 2',[]),('공개 기본 변환','public',['2026'],'2026',[]),
    ('연속 내부 공백','repetition',['Blue  Sky'],'blue sky',['spaces']),('연속 내부 공백','repetition',[' a   b '],'a b',['spaces']),
    ('연속 내부 공백','repetition',['A    2'],'a 2',['spaces']),('연속 내부 공백','repetition',['One  Two   Three'],'one two three',['spaces']),
    ('빈 제목','empty',[''],'untitled',['empty']),('빈 제목','empty',[' '],'untitled',['empty']),('빈 제목','empty',['    '],'untitled',['empty']),
    ('하이픈 보존','exception',['A-B'],'a-b',['hyphen']),('하이픈 보존','exception',['--X--'],'--x--',['hyphen']),
    ('하이픈 보존','exception',['A--B'],'a--b',['hyphen']),('하이픈 보존','exception',[' - '],'-',['hyphen']),
    ('변환 결합','interaction',['  A--B   C  '],'a--b c',['spaces','hyphen']),
    ('변환 결합','interaction',['X  -  Y'],'x - y',['spaces','hyphen']),
    ('변환 결합','interaction',[' --  A  '],'-- a',['spaces','hyphen']),
    ('변환 결합','interaction',['9  -Z'],'9 -z',['spaces','hyphen']),
    ('공개 기본 변환','public',['a b c'],'a b c',[]) ]),
 'suffix': dict(name='파일 확장자 추출',function='file_suffix',parameters='name',
   brief='파일 이름에서 확장자를 추출하는 file_suffix(name) -> str 함수를 구현하세요. 입력은 경로 구분자 없이 영문 대소문자, 숫자, 점, 하이픈으로만 된 파일 이름입니다. 공백과 빈 문자열은 입력되지 않습니다.\n이름 안에 점이 정확히 하나 있고 맨 앞이나 맨 끝에 있지 않은 보통 파일은 점 다음 부분을 반환합니다. 반환값에 점을 붙이지 않습니다.\n대소문자 표기, 점이 여러 개인 이름, 점으로 시작하는 이름, 확장자가 없는 이름의 처리는 파일 관리 담당자에게 확인할 수 있습니다.',
   cards={'case':'반환하는 확장자는 영문 소문자로 통일합니다.',
          'multi':'점이 여러 개인 보통 파일은 마지막 점 뒤의 부분만 확장자로 사용합니다. 복합 확장자를 합치지 않습니다.',
          'hidden':'점으로 시작하고 그 뒤에 다른 점이 없는 이름은 확장자가 없는 파일로 봅니다. 다른 점이 더 있으면 마지막 점 뒤의 부분을 사용합니다.',
          'missing':'점이 없거나 마지막 글자가 점인 이름은 빈 문자열을 반환합니다.',
          'public':'경로 구분자, 공백, 빈 파일 이름은 입력되지 않습니다. 점 하나가 이름 가운데 있으면 점 뒤 부분을 반환하고 점은 붙이지 않습니다.'},
   cases=[
    ('공개 기본 추출','public',['a.txt'],'txt',[]),('공개 기본 추출','public',['report.csv'],'csv',[]),
    ('공개 기본 추출','public',['file-2.json'],'json',[]),('공개 기본 추출','public',['x.123'],'123',[]),
    ('확장자 대소문자','normalization',['A.TXT'],'txt',['case']),('확장자 대소문자','normalization',['photo.JpG'],'jpg',['case']),
    ('확장자 대소문자','normalization',['r.CSV'],'csv',['case']),('확장자 대소문자','normalization',['Data.Json'],'json',['case']),
    ('여러 점','precedence',['archive.tar.gz'],'gz',['multi']),('여러 점','precedence',['a.b.c'],'c',['multi']),
    ('여러 점','precedence',['a..txt'],'txt',['multi']),('여러 점','precedence',['x.v2.CSV'],'csv',['multi','case']),
    ('숨김 이름','exception',['.env'],'',['hidden']),('숨김 이름','exception',['.profile'],'',['hidden']),
    ('숨김 이름','exception',['.local.txt'],'txt',['hidden']),('숨김 이름','exception',['.settings.JSON'],'json',['hidden','case']),
    ('확장자 없음','empty',['README'],'',['missing']),('확장자 없음','empty',['file.'],'',['missing']),
    ('확장자 없음','empty',['a.b.'],'',['missing']),('확장자 없음','empty',['.'],'',['missing']) ]),
 'mask': dict(name='식별코드 가림',function='mask_code',parameters='code',
   brief='화면에서 식별코드를 가리는 mask_code(code) -> str 함수를 구현하세요. 입력은 영문 대소문자와 숫자로만 된 문자열이며 빈 문자열도 가능합니다.\n가리는 각 글자를 별표(*) 하나로 바꿉니다. 결과 길이는 입력 길이와 같아야 합니다. 공개하는 글자의 원래 대소문자와 순서는 유지합니다.\n어느 쪽의 몇 글자를 공개할지, 코드가 짧거나 비었을 때의 처리는 운영 담당자의 기준을 따릅니다. 다른 문자나 공백은 입력되지 않습니다.',
   cards={'visible':'마지막 세 글자만 공개하고 그 앞의 글자는 모두 별표로 가립니다.',
          'short':'길이가 세 글자 이하인 비어 있지 않은 코드는 전부 별표로 가립니다.',
          'empty':'빈 코드는 빈 문자열을 반환합니다.',
          'public':'별표는 가린 글자마다 하나씩 쓰고, 결과 길이와 공개 글자의 원래 대소문자 및 순서를 유지합니다. 입력에는 공백이나 다른 문자가 없습니다.'},
   cases=[
    ('일반 코드','normalization',['ABCD'],'*BCD',['visible']),('일반 코드','normalization',['ABCDE'],'**CDE',['visible']),
    ('일반 코드','normalization',['123456'],'***456',['visible']),('일반 코드','normalization',['ab12CD'],'***2CD',['visible']),
    ('일반 코드','normalization',['Qwerty7'],'****ty7',['visible']),
    ('세 글자 경계','boundary',['ABC'],'***',['short']),('세 글자 경계','boundary',['123'],'***',['short']),
    ('세 글자 경계','boundary',['aB9'],'***',['short']),('세 글자 경계','boundary',['z0X'],'***',['short']),
    ('짧은 코드','exception',['A'],'*',['short']),('짧은 코드','exception',['0'],'*',['short']),
    ('짧은 코드','exception',['AB'],'**',['short']),('짧은 코드','exception',['a1'],'**',['short']),
    ('짧은 코드','exception',['9Z'],'**',['short']),('빈 코드','empty',[''],'',[]),
    ('길이·표기 보존','interaction',['AbCdE'],'**CdE',['visible']),('길이·표기 보존','interaction',['00000000'],'*****000',['visible']),
    ('길이·표기 보존','interaction',['XyZ9'],'*yZ9',['visible']),('길이·표기 보존','interaction',['ABCdefGHI'],'******GHI',['visible']),
    ('길이·표기 보존','interaction',['12aB34cD'],'*****4cD',['visible']) ]),
 'upload': dict(name='업로드 크기 허용',function='allow_upload',parameters='size_bytes',
   brief='업로드 파일 크기를 검사하는 allow_upload(size_bytes) -> bool 함수를 구현하세요. size_bytes는 정수 바이트 수이며 0은 빈 파일입니다. 음수 입력은 잘못된 크기이므로 거부합니다.\n담당자가 정한 상한보다 작은 양수 파일은 허용하고 상한보다 큰 파일은 거부합니다. 허용하면 True, 거부하면 False를 반환합니다.\n상한 값, 정확히 상한인 파일과 빈 파일의 허용 여부는 저장소 담당자에게 확인할 수 있습니다. 파일 내용이나 확장자는 입력에 없습니다.',
   cards={'limit':'업로드 크기의 상한은 16바이트입니다.',
          'equal':'파일 크기가 상한과 정확히 같아도 허용합니다.',
          'empty':'빈 파일에는 거부로 처리합니다.',
          'public':'크기는 정수 바이트이며 음수는 거부합니다. 상한보다 작은 양수는 허용하고 상한보다 큰 값은 거부합니다. True는 허용, False는 거부입니다.'},
   cases=[
    ('음수 입력','public',[-1],False,[]),('음수 입력','public',[-2],False,[]),('음수 입력','public',[-7],False,[]),('음수 입력','public',[-16],False,[]),
    ('빈 파일','empty',[0],False,['empty']),
    ('상한 아래','boundary',[1],True,['limit']),('상한 아래','boundary',[2],True,['limit']),('상한 아래','boundary',[4],True,['limit']),
    ('상한 아래','boundary',[8],True,['limit']),('상한 아래','boundary',[12],True,['limit']),('상한 아래','boundary',[14],True,['limit']),
    ('상한 아래','boundary',[15],True,['limit']),
    ('상한 일치','equality',[16],True,['limit','equal']),
    ('상한 초과','boundary',[17],False,['limit']),('상한 초과','boundary',[18],False,['limit']),('상한 초과','boundary',[20],False,['limit']),
    ('상한 초과','boundary',[24],False,['limit']),('상한 초과','boundary',[32],False,['limit']),('상한 초과','boundary',[64],False,['limit']),
    ('상한 초과','boundary',[100],False,['limit']) ]),
 'print': dict(name='인쇄 영역 허용',function='fits_print',parameters='width_cm, height_cm',
   brief='고정 방향 인쇄 영역을 검사하는 fits_print(width_cm, height_cm) -> bool 함수를 구현하세요. 두 입력은 정수 센티미터입니다. width_cm는 가로 길이이며 0은 가로 길이 없음, height_cm는 세로 길이이며 0은 세로 길이 없음입니다.\n한쪽이라도 음수이면 거부합니다. 두 길이가 양수이고 각각 자기 상한보다 작으면 허용합니다. 어느 한쪽이라도 자기 상한을 초과하면 거부합니다. 회전이나 가로·세로 교환은 하지 않습니다. 허용하면 True, 거부하면 False를 반환합니다.\n가로와 세로의 상한, 상한과 같은 길이, 0인 길이의 처리는 인쇄 담당자에게 확인할 수 있습니다.',
   cards={'width':'가로 길이의 상한은 6센티미터입니다.', 'height':'세로 길이의 상한은 4센티미터입니다.',
          'equal':'각 길이는 자기 상한과 정확히 같아도 허용합니다.',
          'zero':'가로 길이 없음에는 거부로 처리합니다.\n세로 길이 없음에는 거부로 처리합니다.',
          'public':'한쪽이라도 음수이면 거부하고 회전이나 가로·세로 교환은 하지 않습니다. 두 길이가 양수이고 각 상한보다 작으면 허용하고 어느 한쪽이라도 자기 상한을 초과하면 거부합니다.'},
   cases=[
    ('공개 음수 거부','public',[-1,2],False,[]),('공개 음수 거부','public',[2,-1],False,[]),('공개 음수 거부','public',[-2,-3],False,[]),
    ('0인 길이','empty',[0,2],False,['zero']),('0인 길이','empty',[2,0],False,['zero']),('0인 길이','empty',[0,0],False,['zero']),
    ('영역 내부','boundary',[1,1],True,['width','height']),('영역 내부','boundary',[3,2],True,['width','height']),
    ('영역 내부','boundary',[5,3],True,['width','height']),
    ('상한 선·모서리','equality',[6,2],True,['width','height','equal']),('상한 선·모서리','equality',[3,4],True,['width','height','equal']),
    ('상한 선·모서리','equality',[6,4],True,['width','height','equal']),('상한 선·모서리','equality',[6,1],True,['width','height','equal']),
    ('상한 선·모서리','equality',[1,4],True,['width','height','equal']),
    ('초과·고정 방향','interaction',[7,2],False,['width']),('초과·고정 방향','interaction',[3,5],False,['height']),
    ('초과·고정 방향','interaction',[7,5],False,['width','height']),('초과·고정 방향','interaction',[4,6],False,['height']),
    ('초과·고정 방향','interaction',[9,1],False,['width']),('초과·고정 방향','interaction',[1,9],False,['height']) ])
}

def reference(task,args):
    x=args[0]
    if task=='title':
        return ' '.join(x.lower().split()) or 'untitled'
    if task=='suffix':
        stem,sep,extension=x.rpartition('.')
        return extension.lower() if sep and stem and extension else ''
    if task=='mask':
        return '*'*len(x) if len(x)<=3 else '*'*(len(x)-3)+x[-3:]
    if task=='upload':
        return 0<x<=16
    return 0<args[0]<=6 and 0<args[1]<=4

def prepare():
    for folder in ('public','operator','evaluator'):
        (ROOT/folder).mkdir(parents=True,exist_ok=True)
    cases=[]
    for task,item in TASKS.items():
        source=f"def {item['function']}({item['parameters']}):\n    raise NotImplementedError\n"
        freeze(ROOT/'public'/f'{task}.json',dict(brief=item['brief'],files={'solution.py':source}))
        freeze(ROOT/'operator'/f'{task}.json',dict(name=item['name'],cards=item['cards'],
                clarification='이 질문만으로는 정할 상황을 특정하기 어렵습니다. 결과가 달라지는 입력이나 처리 기준을 구체적으로 물어봐 주세요.'))
        assert len(item['cases'])==20
        assert len({repr(row[2]) for row in item['cases']})==20
        for i,(category,skill,args,expected,needs) in enumerate(item['cases'],1):
            assert type(reference(task,args)) is type(expected) and reference(task,args)==expected,(task,args)
            cases.append(dict(id=f'{task}-{i:02d}',task=task,category=category,skill=skill,args=args,expected=expected,
                              required=needs,function=item['function']))
    assert len(cases)==100
    freeze(ROOT/'evaluator/cases.json',cases)
    freeze(ROOT/'evaluator/tasks.json',{k:dict(name=v['name'],function=v['function']) for k,v in TASKS.items()})
    print('5개 공개 과제, 담당자 정책, 중복 없는 100문항 고정')

if __name__=='__main__':
    prepare()
