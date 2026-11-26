# 연구자용 100문항과 기대값

모델에는 공개 명세와 실제 질문의 자연어 회신만 전달했다. 이 표는 최종 제출 후의 분석 자료다.

## 표시 제목 정리

표시 제목을 정리하는 clean_title(text) -> str 함수를 구현하세요. 입력은 영문 대소문자, 숫자, 하이픈, ASCII 공백으로만 된 문자열입니다. 빈 문자열도 가능합니다.
양끝 공백은 제거하고 영문자는 소문자로 바꿉니다. 숫자는 그대로 유지합니다. 내부 공백이 하나인 평범한 단어 사이 공백은 유지합니다.
연속된 내부 공백, 하이픈, 비어 있는 제목을 어떻게 표시할지는 편집 담당자의 기준을 따릅니다. 길이 제한은 없습니다.

| 문항 | 유형 | 입력 | 기대값 | 필요한 정책 |
|---|---|---|---|---|
| title-01 | 공개 기본 변환 | ['Hello'] | 'hello' | 공개 정보 |
| title-02 | 공개 기본 변환 | ['  NEWS  '] | 'news' | 공개 정보 |
| title-03 | 공개 기본 변환 | ['Release 2'] | 'release 2' | 공개 정보 |
| title-04 | 공개 기본 변환 | ['2026'] | '2026' | 공개 정보 |
| title-05 | 연속 내부 공백 | ['Blue  Sky'] | 'blue sky' | spaces |
| title-06 | 연속 내부 공백 | [' a   b '] | 'a b' | spaces |
| title-07 | 연속 내부 공백 | ['A    2'] | 'a 2' | spaces |
| title-08 | 연속 내부 공백 | ['One  Two   Three'] | 'one two three' | spaces |
| title-09 | 빈 제목 | [''] | 'untitled' | empty |
| title-10 | 빈 제목 | [' '] | 'untitled' | empty |
| title-11 | 빈 제목 | ['    '] | 'untitled' | empty |
| title-12 | 하이픈 보존 | ['A-B'] | 'a-b' | hyphen |
| title-13 | 하이픈 보존 | ['--X--'] | '--x--' | hyphen |
| title-14 | 하이픈 보존 | ['A--B'] | 'a--b' | hyphen |
| title-15 | 하이픈 보존 | [' - '] | '-' | hyphen |
| title-16 | 변환 결합 | ['  A--B   C  '] | 'a--b c' | spaces, hyphen |
| title-17 | 변환 결합 | ['X  -  Y'] | 'x - y' | spaces, hyphen |
| title-18 | 변환 결합 | [' --  A  '] | '-- a' | spaces, hyphen |
| title-19 | 변환 결합 | ['9  -Z'] | '9 -z' | spaces, hyphen |
| title-20 | 공개 기본 변환 | ['a b c'] | 'a b c' | 공개 정보 |

## 파일 확장자 추출

파일 이름에서 확장자를 추출하는 file_suffix(name) -> str 함수를 구현하세요. 입력은 경로 구분자 없이 영문 대소문자, 숫자, 점, 하이픈으로만 된 파일 이름입니다. 공백과 빈 문자열은 입력되지 않습니다.
이름 안에 점이 정확히 하나 있고 맨 앞이나 맨 끝에 있지 않은 보통 파일은 점 다음 부분을 반환합니다. 반환값에 점을 붙이지 않습니다.
대소문자 표기, 점이 여러 개인 이름, 점으로 시작하는 이름, 확장자가 없는 이름의 처리는 파일 관리 담당자에게 확인할 수 있습니다.

| 문항 | 유형 | 입력 | 기대값 | 필요한 정책 |
|---|---|---|---|---|
| suffix-01 | 공개 기본 추출 | ['a.txt'] | 'txt' | 공개 정보 |
| suffix-02 | 공개 기본 추출 | ['report.csv'] | 'csv' | 공개 정보 |
| suffix-03 | 공개 기본 추출 | ['file-2.json'] | 'json' | 공개 정보 |
| suffix-04 | 공개 기본 추출 | ['x.123'] | '123' | 공개 정보 |
| suffix-05 | 확장자 대소문자 | ['A.TXT'] | 'txt' | case |
| suffix-06 | 확장자 대소문자 | ['photo.JpG'] | 'jpg' | case |
| suffix-07 | 확장자 대소문자 | ['r.CSV'] | 'csv' | case |
| suffix-08 | 확장자 대소문자 | ['Data.Json'] | 'json' | case |
| suffix-09 | 여러 점 | ['archive.tar.gz'] | 'gz' | multi |
| suffix-10 | 여러 점 | ['a.b.c'] | 'c' | multi |
| suffix-11 | 여러 점 | ['a..txt'] | 'txt' | multi |
| suffix-12 | 여러 점 | ['x.v2.CSV'] | 'csv' | multi, case |
| suffix-13 | 숨김 이름 | ['.env'] | '' | hidden |
| suffix-14 | 숨김 이름 | ['.profile'] | '' | hidden |
| suffix-15 | 숨김 이름 | ['.local.txt'] | 'txt' | hidden |
| suffix-16 | 숨김 이름 | ['.settings.JSON'] | 'json' | hidden, case |
| suffix-17 | 확장자 없음 | ['README'] | '' | missing |
| suffix-18 | 확장자 없음 | ['file.'] | '' | missing |
| suffix-19 | 확장자 없음 | ['a.b.'] | '' | missing |
| suffix-20 | 확장자 없음 | ['.'] | '' | missing |

## 식별코드 가림

화면에서 식별코드를 가리는 mask_code(code) -> str 함수를 구현하세요. 입력은 영문 대소문자와 숫자로만 된 문자열이며 빈 문자열도 가능합니다.
가리는 각 글자를 별표(*) 하나로 바꿉니다. 결과 길이는 입력 길이와 같아야 합니다. 공개하는 글자의 원래 대소문자와 순서는 유지합니다.
어느 쪽의 몇 글자를 공개할지, 코드가 짧거나 비었을 때의 처리는 운영 담당자의 기준을 따릅니다. 다른 문자나 공백은 입력되지 않습니다.

| 문항 | 유형 | 입력 | 기대값 | 필요한 정책 |
|---|---|---|---|---|
| mask-01 | 일반 코드 | ['ABCD'] | '*BCD' | visible |
| mask-02 | 일반 코드 | ['ABCDE'] | '**CDE' | visible |
| mask-03 | 일반 코드 | ['123456'] | '***456' | visible |
| mask-04 | 일반 코드 | ['ab12CD'] | '***2CD' | visible |
| mask-05 | 일반 코드 | ['Qwerty7'] | '****ty7' | visible |
| mask-06 | 세 글자 경계 | ['ABC'] | '***' | short |
| mask-07 | 세 글자 경계 | ['123'] | '***' | short |
| mask-08 | 세 글자 경계 | ['aB9'] | '***' | short |
| mask-09 | 세 글자 경계 | ['z0X'] | '***' | short |
| mask-10 | 짧은 코드 | ['A'] | '*' | short |
| mask-11 | 짧은 코드 | ['0'] | '*' | short |
| mask-12 | 짧은 코드 | ['AB'] | '**' | short |
| mask-13 | 짧은 코드 | ['a1'] | '**' | short |
| mask-14 | 짧은 코드 | ['9Z'] | '**' | short |
| mask-15 | 빈 코드 | [''] | '' | 공개 정보 |
| mask-16 | 길이·표기 보존 | ['AbCdE'] | '**CdE' | visible |
| mask-17 | 길이·표기 보존 | ['00000000'] | '*****000' | visible |
| mask-18 | 길이·표기 보존 | ['XyZ9'] | '*yZ9' | visible |
| mask-19 | 길이·표기 보존 | ['ABCdefGHI'] | '******GHI' | visible |
| mask-20 | 길이·표기 보존 | ['12aB34cD'] | '*****4cD' | visible |

## 업로드 크기 허용

업로드 파일 크기를 검사하는 allow_upload(size_bytes) -> bool 함수를 구현하세요. size_bytes는 정수 바이트 수이며 0은 빈 파일입니다. 음수 입력은 잘못된 크기이므로 거부합니다.
담당자가 정한 상한보다 작은 양수 파일은 허용하고 상한보다 큰 파일은 거부합니다. 허용하면 True, 거부하면 False를 반환합니다.
상한 값, 정확히 상한인 파일과 빈 파일의 허용 여부는 저장소 담당자에게 확인할 수 있습니다. 파일 내용이나 확장자는 입력에 없습니다.

| 문항 | 유형 | 입력 | 기대값 | 필요한 정책 |
|---|---|---|---|---|
| upload-01 | 음수 입력 | [-1] | False | 공개 정보 |
| upload-02 | 음수 입력 | [-2] | False | 공개 정보 |
| upload-03 | 음수 입력 | [-7] | False | 공개 정보 |
| upload-04 | 음수 입력 | [-16] | False | 공개 정보 |
| upload-05 | 빈 파일 | [0] | False | empty |
| upload-06 | 상한 아래 | [1] | True | limit |
| upload-07 | 상한 아래 | [2] | True | limit |
| upload-08 | 상한 아래 | [4] | True | limit |
| upload-09 | 상한 아래 | [8] | True | limit |
| upload-10 | 상한 아래 | [12] | True | limit |
| upload-11 | 상한 아래 | [14] | True | limit |
| upload-12 | 상한 아래 | [15] | True | limit |
| upload-13 | 상한 일치 | [16] | True | limit, equal |
| upload-14 | 상한 초과 | [17] | False | limit |
| upload-15 | 상한 초과 | [18] | False | limit |
| upload-16 | 상한 초과 | [20] | False | limit |
| upload-17 | 상한 초과 | [24] | False | limit |
| upload-18 | 상한 초과 | [32] | False | limit |
| upload-19 | 상한 초과 | [64] | False | limit |
| upload-20 | 상한 초과 | [100] | False | limit |

## 인쇄 영역 허용

고정 방향 인쇄 영역을 검사하는 fits_print(width_cm, height_cm) -> bool 함수를 구현하세요. 두 입력은 정수 센티미터입니다. width_cm는 가로 길이이며 0은 가로 길이 없음, height_cm는 세로 길이이며 0은 세로 길이 없음입니다.
한쪽이라도 음수이면 거부합니다. 두 길이가 양수이고 각각 자기 상한보다 작으면 허용합니다. 어느 한쪽이라도 자기 상한을 초과하면 거부합니다. 회전이나 가로·세로 교환은 하지 않습니다. 허용하면 True, 거부하면 False를 반환합니다.
가로와 세로의 상한, 상한과 같은 길이, 0인 길이의 처리는 인쇄 담당자에게 확인할 수 있습니다.

| 문항 | 유형 | 입력 | 기대값 | 필요한 정책 |
|---|---|---|---|---|
| print-01 | 공개 음수 거부 | [-1, 2] | False | 공개 정보 |
| print-02 | 공개 음수 거부 | [2, -1] | False | 공개 정보 |
| print-03 | 공개 음수 거부 | [-2, -3] | False | 공개 정보 |
| print-04 | 0인 길이 | [0, 2] | False | zero |
| print-05 | 0인 길이 | [2, 0] | False | zero |
| print-06 | 0인 길이 | [0, 0] | False | zero |
| print-07 | 영역 내부 | [1, 1] | True | width, height |
| print-08 | 영역 내부 | [3, 2] | True | width, height |
| print-09 | 영역 내부 | [5, 3] | True | width, height |
| print-10 | 상한 선·모서리 | [6, 2] | True | width, height, equal |
| print-11 | 상한 선·모서리 | [3, 4] | True | width, height, equal |
| print-12 | 상한 선·모서리 | [6, 4] | True | width, height, equal |
| print-13 | 상한 선·모서리 | [6, 1] | True | width, height, equal |
| print-14 | 상한 선·모서리 | [1, 4] | True | width, height, equal |
| print-15 | 초과·고정 방향 | [7, 2] | False | width |
| print-16 | 초과·고정 방향 | [3, 5] | False | height |
| print-17 | 초과·고정 방향 | [7, 5] | False | width, height |
| print-18 | 초과·고정 방향 | [4, 6] | False | height |
| print-19 | 초과·고정 방향 | [9, 1] | False | width |
| print-20 | 초과·고정 방향 | [1, 9] | False | height |
