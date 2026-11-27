def allow_upload(size_bytes):
    if size_bytes < 0:
        return False
    if size_bytes == 0:
        return False
    if 0 < size_bytes < 16:
        return True
    if size_bytes == 16:
        return True
    if size_bytes > 16:
        return False
    raise NotImplementedError
