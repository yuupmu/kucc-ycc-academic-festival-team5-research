def can_cancel(now: str, booked_at: str, starts_at: str) -> bool:
    # 현재 시각이 예약 시작 시각보다 빠르거나 같으면 취소 가능
    if now < starts_at:
        return True
    else:
        return False