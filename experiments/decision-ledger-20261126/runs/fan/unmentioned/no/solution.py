def run_fan(co2_high: bool, quiet_time: bool) -> bool:
    """
    공부방 환풍기 제어 함수
    
    논리:
    1. 두 신호가 모두 True일 경우 (높은 CO2 + 정숙 시간): 
       - 정숙 시간이 우선시되어 환풍기를 끕니다 (False).
    2. 두 신호가 모두 False일 경우 (기존 상태): 
       - 기본 운전으로 환풍기를 켭니다 (True).
    3. co2_high만 True일 경우: 환풍기를 켭니다 (True).
    4. quiet_time만 True일 경우: 환풍기를 끕니다 (False).
    
    Args:
        co2_high (bool): 이산화탄소 농도가 높다는 신호
        quiet_time (bool): 정숙 시간이라는 신호
    
    Returns:
        bool: True (켜기), False (끄기)
    """
    if co2_high and quiet_time:
        # 정숙 시간 우선 (끄기)
        return False
    elif co2_high:
        # CO2 농도 높음 (켜기)
        return True
    elif quiet_time:
        # 정숙 시간만 (끄기)
        return False
    else:
        # 기본 운전 (켜기)
        return False

# 테스트 코드 (주석 처리된 예시)
# assert run_fan(True, True) == False
# assert run_fan(True, False) == True
# assert run_fan(False, True) == False
# assert run_fan(False, False) == True

if __name__ == "__main__":
    print("테스트 완료" if run_fan(True, True) == False else "테스트 실패")