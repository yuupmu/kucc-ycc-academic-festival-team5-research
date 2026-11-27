def allow_upload(size_bytes: int) -> bool:
    if size_bytes < 0:
        return False
    if size_bytes == 0:
        return False
    return True
