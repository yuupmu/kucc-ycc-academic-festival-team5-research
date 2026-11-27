def allow_upload(size_bytes):
    # 음수 입력은 잘못된 크기이므로 거부합니다.
    if size_bytes < 0:
        return False
    
    # 0 은 빈 파일로, 저장소 담당자에게 확인이 필요하므로 미정 경로로 처리합니다.
    if size_bytes == 0:
        return False
    
    # 상한 값은 저장소 담당자에게 확인이 필요하므로 미정 경로로 처리합니다.
    # 상한 값이 정해지지 않았으므로, 모든 양수 파일에 대해 NotImplementedError 를 발생시킵니다.
    if 0 < size_bytes < 16:
        return True
    if size_bytes == 16:
        return True
    return False