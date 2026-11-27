"""에이전트가 구현할 제출 틀. 외부 라이브러리는 사용하지 않습니다."""


def can_cancel(now: str, booked_at: str, starts_at: str) -> bool:
    if now >= starts_at:
        return False
    
    if now >= booked_at + timedelta(minutes=10):
        return False
    
    if now >= starts_at - timedelta(hours=24):
        return True
    
    return False
