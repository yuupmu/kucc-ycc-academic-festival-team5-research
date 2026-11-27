def mask_code(code):
    """
    화면에서 식별코드를 가리는 함수입니다.
    
    입력: 영문 대소문자와 숫자로만 된 문자열 (빈 문자열 포함)
    출력: 마지막 세 글자는 원래 문자 그대로, 앞의 글자는 별표(*)로 바뀐 문자열
    
    동작:
    1. 입력 문자열의 길이를 확인합니다.
    2. 길이가 3 이하인 경우: 입력과 동일한 문자열을 반환합니다.
    3. 길이가 3 초과인 경우:
       - 마지막 3 글자는 원래 문자 그대로 유지합니다.
       - 나머지 앞의 글자(길이 - 3 개)는 별표(*)로 바꿉니다.
    4. 입력에는 공백이나 다른 문자가 없음을 가정합니다.
    
    예시:
    mask_code("abc") -> "abc"
    mask_code("abcd") -> "*cd"
    mask_code("abcdef") -> "***def"
    """
    if len(code) <= 3:
        return code
    else:
        masked_prefix = "*" * (len(code) - 3)
        return masked_prefix + code[-3:]