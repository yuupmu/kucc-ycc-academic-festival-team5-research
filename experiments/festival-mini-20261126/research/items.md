# 고정한 20문항의 실제 반환값

괄호 안의 값은 오답으로 반환한 값이다. 미판정의 오류 기록은 과제·조건·버전별 cases.json에 있다.

| 과제·문항 | 입력 | 기대값 | ① 메인 단독 | ② 메인 자체 검토 | ③ P2 역할 분담 | ③ P3 역할 분담·질문 근거 | ③ P4 질문 정리·답변 반영 확인 | ③ P4 수정 보류 재생 |
|---|---|---|---|---|---|---|---|---|
| 예약 취소 C003 | 생성 후 604,799초 · 시작까지 86,401초 | True | 정답 | 정답 | 정답 | 정답 | 오답 (False) | 정답 |
| 예약 취소 C011 | 생성 후 165,600초 · 시작까지 86,400초 | True | 정답 | 정답 | 정답 | 정답 | 오답 (False) | 정답 |
| 예약 취소 C002 | 생성 후 604,801초 · 시작까지 86,399초 | False | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 정답 | 오답 (True) |
| 예약 취소 C006 | 생성 후 608,400초 · 시작까지 82,800초 | False | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 정답 | 오답 (True) |
| 예약 취소 C071 | 생성 후 600초 · 시작까지 3,600초 | True | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 예약 취소 C072 | 생성 후 601초 · 시작까지 3,600초 | False | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) |
| 예약 취소 C073 | 생성 후 600초 · 시작까지 7,200초 | True | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 예약 취소 C081 | 생성 후 299초 · 시작까지 1초 | True | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 예약 취소 C082 | 생성 후 300초 · 시작까지 0초 | False | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) | 오답 (True) |
| 예약 취소 C084 | 생성 후 301초 · 시작까지 -1초 | False | 정답 | 정답 | 정답 | 정답 | 오답 (True) | 정답 |
| 문의 배정 1 | account | account | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 문의 배정 3 | privacy | privacy | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 문의 배정 4 | misc | general | 미판정 | 미판정 | 미판정 | 미판정 | 미판정 | 미판정 |
| 문의 배정 5 | 빈 목록 | general | 미판정 | 미판정 | 미판정 | 미판정 | 정답 | 정답 |
| 문의 배정 6 | account, billing | billing | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) |
| 문의 배정 7 | billing, account | billing | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 문의 배정 9 | account, privacy | privacy | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) |
| 문의 배정 11 | billing, privacy | privacy | 오답 (billing) | 오답 (billing) | 오답 (billing) | 오답 (billing) | 오답 (billing) | 오답 (billing) |
| 문의 배정 14 | misc, billing | billing | 정답 | 정답 | 정답 | 정답 | 정답 | 정답 |
| 문의 배정 15 | misc, account, privacy, privacy | privacy | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) | 오답 (account) |
