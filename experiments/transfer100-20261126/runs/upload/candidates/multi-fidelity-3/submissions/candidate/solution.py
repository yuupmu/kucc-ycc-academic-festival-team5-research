def allow_upload(size_bytes: int) -> bool:
    if size_bytes == 0:
        return False  # [H2] 빈 파일은 거부합니다.
    if size_bytes < 0:
        return False  # 음수는 거부합니다.
    return True  # [H1] 상한과 정확히 같아도 허용합니다.
