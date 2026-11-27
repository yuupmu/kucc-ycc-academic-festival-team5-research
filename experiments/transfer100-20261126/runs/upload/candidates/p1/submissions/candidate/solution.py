def allow_upload(size_bytes):
    """
    업로드 파일 크기 검사 함수.
    
    상한값: 16 바이트
    - 크기가 0 인 경우: 거부 (False)
    - 크기가 16 이하인 양수인 경우: 허용 (True)
    - 크기가 16 보다 큰 경우: 거부 (False)
    - 음수인 경우: 거부 (False)
    
    Args:
        size_bytes (int): 파일 크기 (바이트)
    
    Returns:
        bool: 파일이 허용되는지 여부
    """
    # 음수 입력은 잘못된 크기이므로 거부합니다.
    if size_bytes < 0:
        return False
    
    # 0 은 빈 파일로, 담당자 답변에 따라 거부합니다.
    if size_bytes == 0:
        return False
    
    # 상한값은 16 바이트입니다.
    # 크기가 16 이하인 양수인 경우 허용합니다.
    if size_bytes <= 16:
        return True
    
    # 상한보다 큰 파일은 거부합니다.
    return False