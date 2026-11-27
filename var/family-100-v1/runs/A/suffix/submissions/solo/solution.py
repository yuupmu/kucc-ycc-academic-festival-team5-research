def file_suffix(name):
    """
    파일 이름에서 확장자를 추출하는 함수입니다.
    
    입력: 경로 구분자 없이 영문 대소문자, 숫자, 점, 하이픈으로만 된 파일 이름
    출력: 점 다음 부분을 반환 (확장자). 점이 여러 개일 경우, 마지막 점 다음 부분을 반환.
    
    예시:
    file_suffix('report.pdf') -> 'pdf'
    file_suffix('image.png.jpg') -> 'jpg'
    file_suffix('file') -> None (확장자가 없음)
    """
    # 이름에 점이 있는지 확인
    if '.' not in name:
        return None
    
    # 점이 여러 개일 경우, 마지막 점 다음 부분을 추출
    # name.rsplit('.', 1) 은 오른쪽에서 첫 번째 점만 기준으로 나누어줌
    parts = name.rsplit('.', 1)
    
    # 두 부분이 있는지 확인 (확장자가 있는지) 및 빈 문자열이 아닌지 확인
    if len(parts) == 2 and parts[1]:
        return parts[1]
    else:
        return None
