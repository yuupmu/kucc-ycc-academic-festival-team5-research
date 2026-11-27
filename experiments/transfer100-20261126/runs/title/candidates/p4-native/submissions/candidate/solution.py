def clean_title(text: str) -> str:
    # 1. 양끝 공백 제거 및 영문자 소문자화, 숫자 유지
    text = text.rstrip().lower()
    
    # 2. 연속된 내부 공백을 하나로 줄임 (H2)
    text = re.sub(r'\s+', ' ', text)
    
    # 3. 하이픈은 개수와 위치를 그대로 유지함 (H1)
    # 빈 문자열은 이미 rstrip 처리 후 빈 문자열로 유지됨
    
    return text

import re