def allow_upload(size_bytes):
    if size_bytes <= 0:
        return False
    if size_bytes > 16:
        return False
    return True
