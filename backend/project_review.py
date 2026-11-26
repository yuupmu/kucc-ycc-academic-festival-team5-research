"""Task-independent review of text projects. Source ranges refer to the previous immutable version."""
import hashlib
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath

from backend.structured_output import array, obj


TEXT_PROTOCOL = 'project-evidence-review-v1'
PROTOCOL = 'project-evidence-review-v2'
PROTOCOLS = (TEXT_PROTOCOL,PROTOCOL)
AUTHOR = '당신은 프로젝트의 유일한 코드 작성자입니다. 공개 명세와 이 조건에서 받은 담당자의 자연어 답변만 운영 결정의 근거입니다.'
INTAKE = ('지금은 전달받은 초안을 그대로 검토합니다. 빠진 정책에 따라 결과가 달라지는 상황을 찾아, 필요한 사실만 평소 말로 질문하세요. '
          '겹치는 규칙의 우선순위, 비어 있는 기본 동작, 근거 없는 단정을 살피세요. 이미 명시된 값이나 구현 방법은 질문하지 마세요. '
          'plan은 짧은 작업 요약입니다. 현재 초안 자체가 완성됐을 때만 complete를 true로 하세요.')
REVISE = ('현재 파일을 공개 원문과 담당자 답변에 대조하세요. 조건이 겹치면 어떤 분기나 대입이 먼저 적용되는지와 '
          '그 순서를 정하는 근거를 확인하세요. 확정된 사항은 이번에 구현하고, 빠진 결정은 그 경로만 보류하고 질문하세요. '
          '충돌을 고칠 때는 영향을 받는 줄만 교체하거나 옮기고, 관련 없는 동작과 들여쓰기를 보존하세요. '
          'edits의 first와 last는 같은 원본 파일의 양끝을 포함하는 줄 번호입니다. k번째 줄 앞에 추가하려면 first=k, last=k-1입니다. '
          '빈 파일에는 first=1, last=0입니다. text에는 그 범위를 대체할 실제 코드만 쓰세요. 줄 번호, 마크다운 울타리를 넣지 마세요. '
          '한 파일의 편집 범위는 겹칠 수 없습니다. 각 편집의 sources에는 그 내용을 결정한 공개 문장 또는 받은 답변의 번호를 넣으세요. '
          '편집이 필요 없으면 빈 배열입니다. questions는 추가 정보가 있어야 결과를 결정할 수 있는 경우만 쓰세요. '
          '모든 요구사항을 구현하고 미결정이 없을 때만 complete를 true로 하세요.')
VIEWS = ('공개 요구의 누락과 초안이 임의로 정한 기본 동작을 확인하세요.',
         '동시에 성립하는 조건, 예외와 기본값, 앞선 반환이나 나중 대입에 가려지는 동작을 확인하세요.',
         '담당자가 실제로 정한 내용이 구현에 반영됐는지, 한 곳을 고치며 다른 동작이 달라졌는지 확인하세요.')
CHECK = ('같은 버전의 원문과 소스만 읽으세요. 직접 코드를 수정하지 않습니다. 각 finding은 한 가지 문제입니다. '
         '두 규칙이 겹치면 해당하는 두 코드 줄을 locations에 넣고 실제 적용 순서를 근거와 비교하세요. '
         '이미 명세 또는 답으로 결정된 구현 문제는 kind=구현 수정, 근거 sources와 실제 위치를 쓰세요. '
         '결정이 빠졌거나 답들이 충돌해 동작이 달라질 때는 kind=담당자 질문, message에 그 차이를 정할 중립적인 질문 한 개만 쓰세요. '
         '이미 받은 답으로 해결되는 것은 다시 묻지 마세요. 모르는 수치나 답을 지어내지 마세요. '
         '문제가 없으면 findings는 빈 배열입니다. 실제로 남은 문제가 없을 때만 ready를 true로 하세요.')
TEXT = {'type':'string','maxLength':400}
BOOL = {'type':'boolean'}
QUESTIONS = array(TEXT,0,5)
PLAN = {'plan':TEXT,'questions':QUESTIONS,'complete':BOOL}
INTAKE_SCHEMA = obj(PLAN)
ASK, FIX = '담당자 질문', '구현 수정'


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validate_project(project):
    if not isinstance(project,dict) or set(project)!={'brief','files'}:
        raise ValueError('프로젝트에는 공개 brief와 편집할 files만 지정하세요.')
    if not isinstance(project['brief'],str) or not project['brief'].strip() or not isinstance(project['files'],dict) or not project['files']:
        raise ValueError('공개 명세와 하나 이상의 작업 파일이 필요합니다. 빈 파일에서 시작할 수 있습니다.')
    for name,source in project['files'].items():
        path=PurePosixPath(name)
        if (not name or '\0' in name or path.is_absolute() or '..' in path.parts or str(path)!=name or name=='.'
                or any(str(parent) in project['files'] for parent in path.parents) or not isinstance(source,str)):
            raise ValueError('파일은 고유한 프로젝트 상대 경로와 텍스트로 지정하세요.')


def sources(brief,answers):
    result={}
    for prefix,text in [('P',brief),*[(f'A{i}.',a['text']) for i,a in enumerate(answers,1)]]:
        for index,line in enumerate((s.strip() for s in text.splitlines() if s.strip()),1):
            result[f'{prefix}{index}']=line
    return result


def context(brief,answers,files):
    numbered={path:'\n'.join(f'{i} | {s}' for i,s in enumerate(text.splitlines(),1)) for path,text in files.items()}
    return {'공개 명세':brief,'담당자 답변 원문':[a['text'] for a in answers],'인용할 원문':sources(brief,answers),'현재 파일과 줄 번호':numbered}


def schemas(files,evidence):
    path={'type':'string','enum':list(files)}
    line={'type':'integer','minimum':1}
    refs={'type':'string','enum':list(evidence)}
    edit=obj({'file':path,'first':line,'last':{'type':'integer','minimum':0},
              'sources':array(refs,1,8),'text':{'type':'string','maxLength':16000}})
    finding=obj({'kind':{'type':'string','enum':[ASK,FIX]},'locations':array(obj({'file':path,'line':line}),0,2),
                 'sources':array(refs,0,8),'message':TEXT})
    return obj({**PLAN,'edits':array(edit,0,8)}),obj({'findings':array(finding,0,4),'ready':BOOL})


def apply_edits(files,edits,evidence):
    """Apply grounded disjoint ranges atomically. All offsets refer to the unmodified input."""
    grouped=defaultdict(list)
    for edit in edits:
        path,start,end=edit['file'],edit['first']-1,edit['last']
        if path not in files or not 0<=start<=end<=len(files[path].splitlines(keepends=True)):
            raise ValueError('원래 파일에 없는 줄 범위')
        if not edit['sources'] or any(source not in evidence for source in edit['sources']):
            raise ValueError('전달된 원문에서 찾을 수 없는 근거')
        grouped[path].append((start,end,edit['text']))
    result=files.copy()
    for path,parts in grouped.items():
        lines=files[path].splitlines(keepends=True)
        newline='\r\n' if '\r\n' in files[path] else '\n'
        previous_start,previous_end=-1,-1
        updated=[]
        for start,end,replacement in sorted(parts):
            if start<previous_end or start==previous_start:
                raise ValueError('같은 원본 줄을 두 번 편집함')
            updated.extend(lines[max(previous_end,0):start])
            if replacement:
                if start==end==len(lines) and updated and not updated[-1].endswith(('\n','\r')):
                    updated.append(newline)
                replacement=newline.join(replacement.splitlines())+(newline if replacement.endswith(('\n','\r')) else '')
                terminated=end<len(lines) or (end>start and lines[end-1].endswith(('\n','\r')))
                if terminated and not replacement.endswith(('\r','\n')):
                    replacement+=newline
                updated.append(replacement)
            previous_start,previous_end=start,end
        result[path]=''.join(updated+lines[previous_end:])
    return result


def review_decision(author,files,reviews,edit_error):
    questions={}
    def add(question,role):
        question=question.strip()
        if question:
            key=''.join(question.casefold().split()).rstrip('?？.')
            item=questions.setdefault(key,{'question':question,'proposed_by':[]})
            if role not in item['proposed_by']:
                item['proposed_by'].append(role)
    for question in author['questions']:
        add(question,'main')
    valid=True
    for index,review in enumerate(reviews,1):
        for finding in review['findings']:
            if finding['kind']==ASK:
                add(finding['message'],f'review-{index}')
            if not finding['message'].strip() or any(not 1<=loc['line']<=len(files[loc['file']].splitlines()) for loc in finding['locations']):
                valid=False
            if finding['kind']==FIX and not (finding['sources'] and finding['locations']):
                valid=False
    ready=(not edit_error and valid and not questions and author['complete'] and any(t.strip() for t in files.values())
           and all(r['ready'] and not r['findings'] for r in reviews))
    return list(questions.values()),bool(ready)


def original_statements(questions,evidence):
    """Set aside a verbatim declarative excerpt. A quoted question or a new request remains eligible."""
    def normalize(text):
        return ' '.join(text.split()).rstrip('.。').strip()
    request=r'[?？؟]|(?:알려|말씀해|정해|확인해|설명해)\s*주|(?:인지요|인가요|나요|궁금합니다)[.。]?$|^\s*(?:please|who|which|what|how|why|when|where|should|could|would|do|does|is|are)\b'
    known={normalize(line):source for source,line in evidence.items()
           if line.rstrip().endswith(('.','。')) and not re.search(request,line,re.I)}
    selected,quoted=[],[]
    for group in questions:
        source=known.get(normalize(group['question']))
        if source is None:
            selected.append(group)
        else:
            quoted.append({**group,'source':source})
    return selected,quoted


def natural_reply(text):
    if (not text.strip() or text.lstrip().startswith(('{','[','```')) or re.fullmatch(r'\s*\d+\s*/\s*\d+\s*',text)
            or re.search(r'가채점\s*(?:결과|점수)|(?:채점\s*결과|테스트\s*통과율|정답률)\s*[:=]?\s*\d|'
                         r'(?:점수|score|test results?)\s*[:=]\s*\d+\s*/\s*\d+|(?m:^\s*assert\s)',text,re.I)):
        raise ValueError('담당자의 결정을 자연어로 입력하세요.')
    return text
