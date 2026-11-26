"""Optional review form derived from the public reservation notice; contains questions only."""
import ast
import io
import re
import tokenize

from experiments import rule_edits as rules


PROMPTS = (
    '이용 시작까지 정확히 24시간 남은 순간에도 일반 취소가 가능한가요?',
    '예약 직후 정정할 수 있는 기간은 얼마인가요?',
    '정정 기간의 마지막 순간에도 정정을 허용하나요?',
    '일반 마감이 지났지만 정정 기간 안이면 어느 규칙을 적용하나요?',
    '정정 기간이 남아 있을 때 이용이 시작되는 바로 그 순간에도 정정할 수 있나요?',
    '정정 기간이 남아 있지만 이용이 이미 시작된 뒤에도 정정할 수 있나요?',
)
ASK = '담당자에게 질문'
CHOICE = {'type':'string','enum':[ASK,'근거가 이미 있음','이 결정과 무관함']}
CHOICES = rules.obj(dict.fromkeys(PROMPTS,CHOICE))
REVIEW_INSTRUCTION = (
    '검토표에는 공개 안내문의 마감, 정정 기간, 이용 시작에 관해 답을 정하지 않은 질문들이 있습니다. '
    '각 질문의 답을 실제로 받은 원문이나 공개 문장만으로 결정할 수 있는지 판단하세요. '
    '담당자 판단이 필요하면 ‘담당자에게 질문’을 선택하세요. 선택한 질문은 그 문장 그대로 담당자에게 갑니다. '
    '표에 없는 정책은 questions에 직접 질문하세요. 답변 문장을 질문으로 복사하지 마세요.'
)
WRITE_INSTRUCTION = (
    '이전 코드가 임시로 남긴 가정을 그대로 쓰지 마세요. 인용 번호가 붙은 담당자 문장을 읽고, '
    '우선 적용할 사건부터 검사해 모든 확정된 경우에 True 또는 False를 반환하는 전체 함수를 작성하세요. '
    '각 답변을 적용한 if 또는 return 줄 끝에 그 문장의 인용 번호를 # [1] 또는 # [1, 3] 형식으로 붙이세요. '
    '같은 조건에 적용되는 문장들은 같은 줄에 함께 붙일 수 있습니다. 인용 번호는 답변과 코드를 다시 읽기 위한 것입니다. '
    '확실한 근거가 없는 경로에서만 raise NotImplementedError를 사용하세요. 사람이 정해야 할 새 질문만 questions에 쓰세요.'
)

RESULTS = {'허용':'return True', '거부':'return False', '미정':'raise NotImplementedError("담당자 판단 필요")'}
ACTION = {'type':'string','enum':list(RESULTS)}
REFERENCES = rules.array({'type':'integer','minimum':1,'maximum':100},0,16)
CONDITION = rules.obj({'input':rules.FIELD,'op':rules.TEST['properties']['op'],'seconds':{'type':'integer'}})
ROW = rules.obj({'when':rules.array(CONDITION,1,3),'action':ACTION,'references':REFERENCES})
FALLBACK = rules.obj({'action':ACTION,'references':REFERENCES})
TABLE_INSTRUCTION = (
    '당신이 함수의 모든 동작을 정합니다. 먼저 plan에 동시에 성립하는 조건 중 어느 결정이 우선하는지와 '
    '아무 조건에도 해당하지 않을 때의 동작을 담당자 원문에 근거해 설명하세요. '
    'rows의 각 행에는 입력·비교기호·정수 초, 그 조건에서의 판정, 근거가 된 담당자 원문 번호를 적으세요. '
    '여러 조건을 한 행에 쓰면 모두 참일 때만 해당합니다. 위에서부터 처음으로 해당하는 행이 즉시 반환됩니다. '
    '여러 문장이 같은 결정을 정하면 한 행에 인용 번호를 모으세요. 조건을 모두 지난 경우는 fallback이 정합니다. '
    '지난 초안의 임시 동작을 물려받지 말고 허용·거부가 확정된 경우와 실제로 미정인 경우를 구분하세요. '
    '판정을 바꿀 미정 사항만 questions에 쓰세요. 받은 답으로 모든 경로를 결정했을 때 complete를 true로 하세요.'
)


def render_table(decision, statements):
    """Print exactly the main author's branches in order. No policy, tests or inferred defaults here."""
    lines = ['def allow_cancel(age_seconds, until_start_seconds):']
    for row in decision['rows']:
        checks = [f"{c['input']} {c['op']} {c['seconds']}" for c in row['when']]
        lines.append('    if '+' and '.join(checks)+':'+reference_comment(row['references']))
        lines.append('        '+RESULTS[row['action']])
    default = decision['fallback']
    lines.append('    '+RESULTS[default['action']]+reference_comment(default['references']))
    code='\n'.join(lines)+'\n'
    return code, source_links(code,statements)


def reference_comment(refs):
    return '  # ['+', '.join(map(str,refs))+']' if refs else ''


def sentences(texts):
    return list(dict.fromkeys(s.strip() for text in texts for s in re.split(r'(?<=[.!?。])\s+|\n+',text) if s.strip()))


def is_question(text):
    return bool(re.search(r'[?？]|(?:알려|설명해|확인해|정해|말씀해)\s*주(?:세요|십시오)|궁금합니다|인지요[.]?$',text))


def citable_sentences(texts):
    # The raw reply stays in the model conversation. A request for clarification cannot authorize a rule.
    return [s for s in sentences(texts) if not is_question(s) and not re.search(r'미정|정해지지\s*않|아직\s*모르',s)]


def source_links(code, statements):
    """Map the author's inline references to executable lines and verbatim policy text."""
    try:
        tree = ast.parse(code)
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except (SyntaxError, ValueError, tokenize.TokenError, IndentationError):
        return []
    lines = code.splitlines()
    locations = {node.lineno for node in ast.walk(tree) if isinstance(node,(ast.If,ast.Return,ast.Assign,ast.AnnAssign))}
    links = []
    for token in tokens:
        row, col = token.start
        if token.type != tokenize.COMMENT or row not in locations:
            continue
        for group in re.findall(r'\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]',token.string):
            for index in map(int,group.split(',')):
                if 1 <= index <= len(statements):
                    links.append({'quote':statements[index-1], 'line':lines[row-1][:col].strip()})
    return links
