import re

def clean_title(text: str) -> str:
    # [P1, H1] 빈 문자열 처리 및 입력 검증
    if not text:
        return text
    
    # [P2, H2] 양끝 공백 제거 및 영문자 소문자화 (숫자 유지)
    text = text.rstrip().lower()
    
    # [H1] 하이픈은 개수와 위치를 그대로 유지함 (연속된 하이픈 제거 로직 제거)
    # [P2, P3] 연속된 내부 공백을 하나의 공백으로 통일 (하이픈 제외)
    # 정규식: 공백이 아닌 문자열 부분에서 연속된 공백을 단일 공백으로 치환
    text = re.sub(r'(?<!-)\s+(?!\s*-)', ' ', text)
    
    # [P2, P3] 앞뒤 공백 제거
    text = text.strip()
    
    return text