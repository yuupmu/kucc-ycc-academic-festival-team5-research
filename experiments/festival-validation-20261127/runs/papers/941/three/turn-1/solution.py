def offer_excerpt(pages: int) -> bool:
    """
    독서 모임 책자의 발췌본을 제안할지 정하는 함수입니다.
    
    조건:
    - 4 쪽보다 얇거나 (pages <= 4): 제안하지 않음 (False)
    - 12 쪽보다 두꺼운 (pages > 12): 제안하지 않음 (False)
    - 4 쪽보다 두껍고 12 쪽보다 얇으면 (4 < pages <= 12): 제안함 (True)
    
    Args:
        pages (int): 원고 쪽수
    
    Returns:
        bool: 제안할 경우 True, 아니면 False
    """
    if 4 < pages <= 12:
        return True
    else:
        return False


# 테스트 코드 (예시)
if __name__ == "__main__":
    # 4 쪽 이하인 경우
    assert offer_excerpt(3) == False
    assert offer_excerpt(4) == False
    
    # 4 쪽 초과 12 쪽 이하인 경우
    assert offer_excerpt(5) == True
    assert offer_excerpt(10) == True
    assert offer_excerpt(12) == True
    
    # 12 쪽 초과인 경우
    assert offer_excerpt(13) == False
    assert offer_excerpt(20) == False
    
    print("모든 테스트 케이스가 통과되었습니다.")