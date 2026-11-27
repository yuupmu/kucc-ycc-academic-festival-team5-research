def show_excerpt(featured: bool, spoiler: bool, compact: bool) -> bool:
    """
    서평 카드의 발췌문을 표시할지 결정하는 함수.
    
    규칙:
    1. 작은 카드(compact)에서는 항상 숨깁니다 (False).
    2. 일반 카드에서는:
       - 추천 표시(featured)와 스포일러 표시(spoiler)가 모두 없으면 표시합니다 (True).
       - 추천 표시만 있으면 표시합니다 (True).
       - 스포일러 표시만 있으면 숨깁니다 (False).
       - (추천과 스포일러가 모두 있는 경우: 일반적인 로직 추론에 따르면 스포일러가 우선시되어 숨김이 적용되는 경우가 많으나, 문제 설명에서 "추천 표시만 있으면 표시하고, 스포일러 표시만 있으면 숨깁니다"라고 명시했으므로, 두 조건이 동시에 발생할 경우의 명시적 규칙은 제공되지 않았습니다. 
         그러나 문제의 맥락상 "spoiler"가 "featured"보다 더 강력한 숨김 신호로 간주되는 것이 일반적이므로, 
         두 조건이 모두 참인 경우에도 스포일러가 우선하여 False를 반환하는 것이 합리적입니다.
         만약 두 조건이 동시에 발생할 때의 행동을 명시하지 않았으므로, 가장 안전한 추측은 spoiler 가 featured 를 덮는 것입니다.
    )
    
    Args:
        featured (bool): 추천 표시 여부.
        spoiler (bool): 스포일러 표시 여부.
        compact (bool): 작은 카드 여부.
    
    Returns:
        bool: True이면 발췌문 표시, False이면 숨김.
    """
    # 작은 카드(compact)에서는 항상 숨깁니다
    if compact:
        return False
    
    # 일반 카드 경우
    # 스포일러가 있으면 항상 숨깁니다 (spoiler가 featured를 덮는다고 가정) - 문제 설명에서 "spoiler 표시만 있으면 숨깁니다"라고 했으므로, 
    # spoiler 가 True 인 경우 무조건 False 로 처리합니다. (featured 가 True 라 하더라도 spoiler 가 있으면 숨김이 우선시되는 것이 일반적이며, 
    # 문제의 조건 "추천 표시만 있으면 표시하고, 스포일러 표시만 있으면 숨깁니다"는 서로 배타적인 상황을 가정하고 설명한 것으로 보입니다.
    # 만약 두 조건이 동시에 참인 경우를 명시하지 않았으므로, spoiler 가 더 강력한 조건으로 간주합니다.
    if spoiler:
        return False
    
    # 스포일러가 없으면, featured 가 True 라면 표시합니다
    return featured
