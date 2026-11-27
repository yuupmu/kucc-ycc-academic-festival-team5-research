def allow_upload(size_bytes):
    if size_bytes < 0:
        return False
    
    # 상한 값은 저장소 담당자가 결정합니다.
    # 여기서는 10MB (1024000 바이트)로 설정합니다.
    max_size_bytes = 1024000
    
    if size_bytes <= max_size_bytes:
        return True
    else:
        return False
