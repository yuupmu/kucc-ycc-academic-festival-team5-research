def allow_upload(size_bytes):
    # 음수 입력은 잘못된 크기이므로 거부합니다.
    if size_bytes < 0:
        return False
    
    # 0 은 빈 파일로, 담당자 답변에 따라 거부합니다.
    if size_bytes == 0:
        return False
    
    # 상한 값은 16 바이트입니다.
    MAX_SIZE = 16
    
    # 상한보다 작은 양수 파일은 허용하고, 정확히 상한인 파일도 허용합니다.
    # 즉, 0 < size_bytes <= MAX_SIZE 인 경우 True 를 반환합니다.
    return size_bytes <= MAX_SIZE