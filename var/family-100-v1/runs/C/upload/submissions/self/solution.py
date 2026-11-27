def allow_upload(size_bytes, max_size=None):
    if size_bytes < 0: return False
