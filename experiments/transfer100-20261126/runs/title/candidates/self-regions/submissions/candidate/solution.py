def clean_title(text: str) -> str:
    # 1. 양끝 공백 제거 및 영문자 소문자화, 숫자 유지
    text = text.rstrip().lower()
    
    # 2. 하이픈은 개수와 위치를 그대로 유지 (H1)
    # 3. 연속된 내부 공백, 하이픈, 빈 문자열은 하나의 공백으로 통일 (P3 기준)
    # 정규식: 하나 이상의 공백, 하이픈, 빈 문자열 (\\s, -, \u0000) 을 하나의 공백으로 치환
    text = re.sub(r'[ \t\n\r\f\v-]+', ' ', text)
    
    # 4. 결과에서 앞뒤 공백 제거 (안전성 확보)
    text = text.strip()
    
    return text

import re