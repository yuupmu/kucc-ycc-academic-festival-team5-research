def offer_excerpt(pages: int) -> bool:
    """
    독서 모임 책자의 발췌본을 제안할지 정하는 함수입니다.
    
    조건:
    - 4쪽보다 얇거나 (pages <= 4): 제안하지 않음 (False)
    - 12쪽보다 두꺼운 (pages >= 12): 제안하지 않음 (False)
    - 4쪽보다 두껍고 12쪽보다 얇은 (4 < pages < 12): 제안함 (True)
    
    Args:
        pages (int): 원고 쪽수
    
    Returns:
        bool: 제안 여부를 반환
    """
    if pages <= 4 or pages >= 12:
        return False
    return True
