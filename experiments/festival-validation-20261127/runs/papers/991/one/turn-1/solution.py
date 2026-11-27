def offer_excerpt(pages: int) -> bool:
    """
    독서 모임 책자의 발췌본을 제안할지 정하는 함수입니다.
    
    조건:
    - 4 쪽보다 얇거나 (pages <= 4): 제안하지 않음
    - 12 쪽보다 두꺼운 (pages >= 12): 제안하지 않음
    - 4 쪽보다 두껍고 12 쪽보다 얇은 (4 < pages < 12): 제안함
    
    Args:
        pages (int): 원고 쪽수
    
    Returns:
        bool: 제안할 경우 True, 아닐 경우 False
    """
    if pages <= 4 or pages >= 12:
        return False
    return True