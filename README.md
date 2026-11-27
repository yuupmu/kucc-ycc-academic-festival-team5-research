# kucc ycc 학술제 5조 연구내용

**감시자가 알아낸 규칙은 최종 코드에 남았는가?** 같은 초안에서 단독 작성, 자체 검토 후 질문, 독립 감시 후 질문을 비교했다. 담당자가 실제로 알려 준 정책, 제출 코드의 동작, 사용 토큰을 함께 기록했다.

| 찾아볼 내용 | 자료 |
|---|---|
| 연구 방향을 바꾼 이유와 단계별 구조 | [파이프라인 변천사와 현재 흐름도](docs/파이프라인.md) |
| 발표용 종합보고서 | [Markdown](docs/pdf/학술제_감시자가_찾은_규칙은_코드에_남았나.md) · [PDF](docs/pdf/학술제_감시자가_찾은_규칙은_코드에_남았나.pdf) |
| 담당자 답을 뒤집은 후속 실험 | [Markdown](docs/pdf/학술제_후속실험_담당자_답을_뒤집은_짝비교.md) · [PDF](docs/pdf/학술제_후속실험_담당자_답을_뒤집은_짝비교.pdf) |
| 발표와 멘토링 | [실험 발표자료](experiments/5조_멀티에이전트_실험_발표자료.pptx) · [미팅·피드백](docs/meetings) · [파이프라인 슬라이드](docs/pipeline-slide) · [슬라이드별 발표 해설](docs/presentation_notes/슬라이드별_목차.md) |
| 개발 과정과 벤치마크 | [개발 기록](docs/reports) · [예약·문의 100문항](experiments/pipeline100/README.md) · [전이 100문항](experiments/transfer100-20261126/README.md) · [모델별 10조건](experiments/family-reply-delta-20261126/README.md) · [예약 조건별 점수](var/reservation-family-v1/scores.json) |
| 최신 제출과 비용 | [회신 처리 검증](experiments/ledger-receipts-20261126/results.json) · [회신 전후 코드](experiments/ledger-receipts-20261126/runs) · [기록된 실험 데이터](var) |

기록을 읽고 비교하는 데에는 모델 설치가 필요하지 않다. 로컬 추론을 재실행할 때는 실험 코드가 사용하는 llama-server와 GGUF 파일을 `var/local-models/`에 배치한다. [세 모델의 파일명·해시](var/family-100-v1/weights.json) · [로컬 실행 설정](experiments/local_transport.py)


코드를 작성하는 메인 에이전트를 단독으로 실행하거나 서로 다른 관점의 감시자 3명을 함께 실행하는 실험 환경입니다.

예약 취소와 문의 배정을 합친 100문항에서 26개 구조를 비교했다. 메인 단독은 66개, 실제 후속 질문을 한 메인 자체 검토는 73개, 독립 감시자 세 명은 62개를 맞혔다. 각 질문과 담당자 답이 어느 코드 분기에 반영됐는지 문항별로 확인할 수 있다. [100문항 비교 보고서와 엑셀 원자료](<experiments/pipeline100/README.md>)

일정·배정과 다른 새 유형 5개의 입력 100개에서 21조건을 비교했다. 메인 단독 33점, 현재 자체 검토 3회차 68점, 현재 감시자 3회차 81점이었다. 최고 조건은 P4 질문+입력 영역의 82점이며, 질문·답변·코드·유형별 실패와 실제 토큰을 함께 기록했다. [새 유형 100문항 비교와 PDF 보고서](<experiments/transfer100-20261126/README.md>)

회차별 질문·회신, 모델 요청·응답, 제출 코드와 채점 결과를 공개했다. [연구 원자료 색인과 공개 범위](docs/research-data/README.md)에서 실험별 기록과 공개본 해시를 확인할 수 있다.

## 학술제의 세 비교 조건

혼합 감시에서 질문과 회신을 항목별로 연결하려면 `python3 -B -m experiments.mixed_review_ledger upload 실행폴더`로 시작한다. 과제 이름 대신 공개 명세 JSON도 받는다. 기존 초안과 감시 기록은 `python3 -B -m experiments.receipt_pipeline 실행폴더 --handoff 감시기록.json`으로 이어 쓸 수 있다. 작성기는 묶인 질문을 결정 항목으로 나누고 공개 규칙과 함께 고정한다. `python3 -B -m experiments.receipt_pipeline 실행폴더 --turn 1 --answer-file 담당자회신.txt`로 자연어 답을 전달하면, 실행 폴더에 회신 원문·확정된 항목·제출 코드를 저장하고 남은 항목의 질문을 돌려준다. 다음 답은 같은 폴더에 회차를 하나 올려 전달한다. 현재 코드 편집 대상은 정수 입력 하나 또는 불리언 입력을 받는 결정 함수다.

담당자 회신을 코드로 옮기는 새 3회차 실험은 `python3 -B -m experiments.reply_pipeline upload 실험폴더`로 시작한다. 과제 이름 대신 공개 명세 JSON 경로를 줄 수 있다. 정수 하나의 참·거짓을 판단하는 미구현 분기에서는 메인이 허용·거부 범위를 각각 적고, 편집기가 두 범위를 확인한 뒤 반환문을 조립한다. 자체 검토와 독립 감시에 같은 작성기를 쓴다. [실행 방법과 같은 회신으로 비교한 결과](<experiments/scoped-behavior-20261126/README.md>)

새 3회차 실행에서는 메인이 감시자의 구체적 수정 지적과 담당자의 자연어 답을 함께 받아, 근거가 확인된 입력 범위의 코드만 고친다. 마지막 검토에서 새 오류를 발견하면 당시까지의 답으로 한 번 더 수정·검토할 수 있다. [작성기 변경과 동일 대화 비교](<experiments/review-repair-20261126/README.md>)

① 메인이 공개 자료만으로 한 번 작성한다. ②는 같은 초안을 메인이 스스로 검토하고 담당자에게 묻는다. ③은 같은 초안을 감시자 A·B·C가 독립적으로 검토하고 담당자에게 묻는다. ②와 ③ 모두 메인이 코드를 고친다. 공개 자료 외에 분기를 결정하는 데 쓸 수 있는 외부 정보는 그 조건이 받은 담당자의 자연어 답변이다. 실제 입력·출력 토큰과 회차별 코드를 보관한다. [핵심 20문항 비교와 코드 원인 분석](<experiments/festival-mini-20261126/README.md>)

같은 20문항에서 담당자와 세 차례 질의응답하는 비교를 실행했다. ②와 ③의 1·2·3회차 코드, 회차별 질문과 담당자 답, 실제 토큰을 추적한다. 일반 프로젝트에서 `python3 -B -m experiments.repeated_intervention 실행폴더 --project 공개명세.json --role multi --cycles 3`로 시작한다. [1회차와 3회차의 성능·토큰·코드 변화](<experiments/three-cycles-20261126/README.md>)

기본 반복 실행에서 담당자가 확정한 입력 조건과 실제 반환값을 대조하고, 이미 반영한 답이 다음 회차에 뒤집히는지도 확인한다. 같은 세 회차의 질문과 답을 고정한 20문항에서 자체 검토는 12 → 13점, 독립 감시자는 14 → 15점이었다. [담당자 회신 반영 전후의 코드·점수·비용](<experiments/answer-fidelity-20261126/README.md>)

앞선 비교는 감시자가 가능한 두 규칙을 구별하는 질문을 만드는 변화와, 같은 담당자 답을 실제 실행 조건에 옮기는 변화를 따로 검증했다. [질문과 작성 방식을 분리한 20문항 비교](<experiments/rule-cycle-20261126/README.md>)

공개 명세 `brief`와 작업할 파일의 상대 경로·텍스트를 담은 `files`로 새 과제를 시작한다. 다음은 질문 창구와 수정 기회를 한 번씩 두는 설정이다. 파일로 답할 때는 해당 조건이 물은 내용에 대해서만 자연어로 답한다.

```sh
python3 -B -m experiments.festival_protocol experiments/새비교 --project 공개명세.json --arms solo self p2 p3 --versions 2
python3 -B -m experiments.festival_protocol experiments/새비교 --reply-arm p2 --reply-to 1 --answer-file 담당자답변.txt
python3 -B -m experiments.festival_guarded experiments/질문정리비교 --parent experiments/새비교
python3 -B -m experiments.festival_guarded experiments/질문정리비교 --parent experiments/새비교 --answer-file 질문정리조건답변.txt
```

기본 모델은 Qwen3.5-4B Q4_K_M이며 전 역할이 같은 로컬 가중치를 사용한다. P1은 공통 관점, P2는 관점 분담, P3는 각 질문의 상황과 가능한 두 결과를 적는다. P4는 P3의 같은 **첫** 초안·감시 의견에서 갈라진다. C가 질문을 묶고 메인이 답과 실행 코드의 대응을 기록한다. 파일은 `submissions`에 고정하며 완료 상태는 `state.json`에 별도로 기록한다. 보완한 실행에서 실제 유지한 파일과 미확인 근거는 `guarded`에 있다.

## 초기 두 조건 예비 실험

로컬 공통 파이프라인은 공개 요구사항을 담은 `brief`와 편집할 텍스트 파일의 경로·내용을 담은 `files`를 받습니다. 예를 들어 아래와 같이 공개 명세 파일을 만들어 실행합니다. 하위 폴더와 여러 파일을 지정하거나 빈 파일로 시작할 수 있습니다. [서로 다른 세 과제의 공개 명세와 검증 기록](<experiments/project-transfer-20261126/README.md>)

```json
{
  "brief": "표시 이름을 정리하는 함수를 구현하세요. 표기가 충돌하면 편집팀의 기준을 확인하세요.",
  "files": {"src/names.py": "def display_name(values):\n    raise NotImplementedError\n"}
}
```

```sh
python3 -B -m experiments.project_review experiments/내실행 --project 공개명세.json
python3 -B -m experiments.project_review experiments/내실행 --reply-arm multi --reply-to 1 --answer-file 담당자답변.txt
```

첫 회차에는 전달한 파일을 그대로 읽습니다. 메인과 검토자가 질문을 직접 쓰고, 해당 조건은 담당자 답변을 기다립니다. 다음 회차부터 메인은 공개 명세와 그 조건이 받은 자연어 답을 근거로 줄 범위를 편집합니다. 독립 감시자들은 같은 버전을 검토하고, 근거가 있는 구현 문제와 사람이 정할 정책을 구분합니다. 버전별 파일과 질문은 실행 폴더에, 완료된 프로젝트 파일은 `submissions/self` 또는 `submissions/multi`에 보관합니다. 접수된 질문이 남거나 수정이 필요하다고 판단하면 최대 여섯 버전까지 검토합니다.

기본 로컬 모델은 Qwen3-8B입니다. `--author-model`에 메인 모델 경로, `--review-models`에 세 감시자의 GGUF 경로를 순서대로 지정할 수 있습니다. 같은 경로는 한 서버를 공유하고 호출은 순서대로 진행합니다. 기존 진입점인 `experiments.monitor_cycles`에서도 `--project`로 같은 절차를 실행합니다.

## 기본 예약 취소 실험

로컬 Qwen3-8B로 정보가 부족한 예약 취소 과제를 수행합니다. 메인만 코드를 수정합니다. 단일 조건에서는 같은 메인이 세 번 자체 검토하고, 멀티 조건에서는 감시자 세 명이 같은 코드 버전을 독립적으로 읽습니다. 각 조건은 자신이 실제로 물은 운영 기준에 대해서만 담당자의 자연어 답을 받습니다. [변경 전후 흐름과 실제 비교](<experiments/human-intervention-20261126.md>)

시간 비교에 담당자 원문을 연결하는 실험은 두 가지입니다. `--source-thresholds`에서는 메인이 원문에 있는 시각과 수량을 고릅니다. `--bind-authored-times`에서는 기존 규칙표를 그대로 작성하면 검토 직전에 실행기가 입력·수량의 근거와 인용한 끝점 정책을 적용합니다. 이 두 번째 방식은 시드 263의 여섯 번째 코드에서 멀티 정답을 25개에서 29개로 늘렸고 단일은 24개였습니다. 같은 시드의 `--ordered-rules` 실행 폴더를 `--draft-from`에 지정하면 동일한 초안에서 비교할 수 있습니다. [전후 흐름과 측정 기록](<experiments/threshold-study-20261126.md>)

```sh
python3 -B -m experiments.monitor_cycles --human-intervention --seed 131 experiments/기준선
python3 -B -m experiments.monitor_cycles --human-intervention --ordered-rules --seed 131 --draft-from experiments/기준선 experiments/우선순위비교
```

예약 전용 `--human-intervention`의 기본 실행은 자유 질문 기준선입니다. `--question-guide`는 검토자가 중립적인 질문을 선택하거나 새 질문을 작성하게 합니다. `--ordered-rules`는 같은 질문 방식을 쓰고, 메인이 조건·순서·반환값·어디에도 해당하지 않을 때의 동작을 직접 정합니다. 같은 시드의 기준선에서 첫 초안이 생성된 후 그 기록을 `--draft-from`으로 지정할 수 있습니다. 각 방식의 새 실행에는 다른 폴더를 지정합니다.

질문이 생기면 해당 조건이 대기합니다. 예를 들어 멀티 조건의 첫 질문에 답하려면 아래처럼 자연어 텍스트를 전달합니다. 단일 조건은 `self`를 사용합니다. 승인된 고정 정책으로 진행자가 대신 답하는 실험에서는 시작 또는 재개 명령에 `--operator-card`를 붙입니다. 새 실행은 질문의 배경 설명과 실제 의문문을 구분합니다. 접수 시간 범위만 물은 문장에서는 정정 허용 정책을 공개하지 않습니다. 누가 답했는지와 실제로 질문한 문장을 실행 폴더의 `state.json`에 보관합니다.

```sh
python3 -B -m experiments.monitor_cycles experiments/우선순위비교 --reply-arm multi --reply-to 1 --answer-file 담당자답변.txt
```

연구자는 코드가 저장될 때마다 형제 폴더 `<실행폴더>-research/overview.md`에서 점수, 판정 수, 개선·퇴행 문항 수를 봅니다. 각 버전의 `change.diff`와 `grade.json`에서 구체적인 변경을 확인합니다. 모델 호출에는 공개 과제, 그 조건의 산출물과 받은 자연어 답변만 들어갑니다. 결정 및 코드에 남은 문제가 있으면 최대 6번째 버전까지 진행한 후 미제출로 기록합니다.

이전 A·B·C·D 순차 코드 수정 실험은 `--public-clock-revisions`로 재현할 수 있습니다. A는 공개 문구를 해석하고 B·C·D는 코드를 수정했으며, 모든 제출을 고정한 뒤 채점했습니다. 당시에는 담당자가 개입하지 않았습니다. [이전 6회 호출 실험](<experiments/qwen3-public-clock-review-20261126/README.md>)

`--serial-revisions`는 원래 코드를 보존하며 순차 수정하는 5회 호출 비교입니다. `--rule-table-revisions`는 함수 전체를 규칙표로 다시 작성합니다. 기존 `--blind-candidates`에서는 D가 같은 초안에서 나온 후보 또는 초안 하나를 고릅니다. 이전 `--candidates`와 `--verified`는 모델에 예시 기대값과 실행 결과를 전달했으므로 가채점 비공개 실험 성적에서 제외합니다. [5회 호출 순차 수정](<experiments/qwen3-source-revisions-20261126/README.md>) · [기존 후보 선택 실험](<experiments/qwen3-blind-abcd-20261126/README.md>)

새 브라우저 설정은 **메인 단독 · GPT-4o mini · 기본 예약 취소 40문항**으로 시작합니다. 기존 설정을 불러온 화면에서는 **메인 단독 기준선 불러오기**로 선택할 수 있습니다. 키를 연결한 뒤 접근 가능한 메인 모델을 확인하고 실행하세요. 이 과제에서는 메인도 계획과 구현 단계에서 사람에게 직접 질문할 수 있습니다. 질문에는 **규칙** 화면의 고정 답변 카드로 응답합니다.

40문항은 기존 예약 취소에서 일반 마감, 마감 경계, 예약 직후 유예, 이용 시작과 유예의 우선순위 유형을 각각 10개씩 사용합니다. 휴무 달력은 제외합니다. **테스트하기**에서 실제 완료된 코드의 정답 수, 정답률과 유형별 결과를 확인합니다. 정답 하나당 1점입니다.

별도의 [로컬 모델 실험](<experiments/pilot-qwen/README.md>)은 API 키 없이 같은 40문항을 사용합니다. 질문 한 번과 구현 한 번으로 구성한 실험이며, 웹 실행기의 반복 수정과는 호출 예산이 다릅니다.

로컬 A·B·C 비교는 `python3 -m experiments.timed_abc 새결과폴더`로 시작합니다. B와 C는 검토 3회 후 첫 수정 1회를 공유하는 설계입니다. 담당자는 각 조건의 `.reviews.json`에서 초안과 세 의견 전문을 읽고, 같은 이름의 `.decisions.json`에 `{"R1":"","R2":"","R3":""}` 형태로 답합니다. 확인한 항목에만 답변을 채웁니다. 고정 답변 외에 실행 예가 필요하면 별도 행에 `검사 <예약 후 경과 초> <시작까지 남은 초> <허용 또는 거부>`를 씁니다. 설명만 전달하는 답변에는 별도 행에 `맥락만`을 씁니다.

첫 수정 점수는 결과의 `delivery.first_submission_score`에 남습니다. 확인된 검사가 실패하면 같은 모델에 최대 5번 더 수정을 요청합니다. 최종 점수는 `report.score`, 추가 호출 수·토큰·모델 응답 시간은 `delivery.repair_cost`에서 확인합니다. `paused_unresolved`는 수정 한도까지 실패가 남았다는 뜻입니다. `submitted_no_confirmed_findings`는 검토를 마치고 추가로 검사할 지적이 없었다는 뜻입니다. [실제 전달·재수정 검증 기록](<experiments/abc-delivery-check/README.md>)

## 실행

Mac에서 `start.command`를 실행하고 http://127.0.0.1:8000 을 엽니다. 또는 `python3 -B serve.py`를 실행합니다. Python 3.9 이상, 외부 패키지는 필요 없습니다. 실제 모델이 생성한 코드의 격리 검증에는 macOS가 필요합니다.

파일로 연 `web/index.html`에서는 입력 설정만 사용할 수 있습니다. API 연결·실행·답변·채점은 서버 주소에서 사용합니다.

1. **테스트 상황**에서 기본 예약 취소(40문항), 예약 취소(100문항), 예약·대기열·자원 배정(150세트) 중 하나를 선택합니다. API 키를 입력하고 **연결**을 누릅니다.
2. 실행 모드를 **OpenAI API**로 두고 메인·감시자별 모델을 선택하고 프롬프트를 입력합니다. 연결 후에는 계정 목록과 호환 목록을 대조하여 Responses·구조화 출력을 지원하고 종료되지 않은 모델만 표시합니다. 음성·이미지·임베딩 전용 모델, 종료된 모델, 지원이 확인되지 않은 ID는 제외합니다. **모델 새로고침**으로 목록을 갱신할 수 있습니다. 연결 전 기본 후보는 Sol·Astra·Terra·Luna·GPT-4o·GPT-4o mini이며 실제 접근 가능 여부는 연결 후 확인합니다.
3. **실행** → 질문 선택 → 인간 답변 제출 → 코드 수정·검증.
4. 프로젝트 완료 후 **테스트하기**를 눌러 해당 실행에 고정된 40문항, 100문항 또는 150세트를 채점합니다. 과제 선택을 바꾸어도 이미 생성한 실행의 채점기는 바뀌지 않습니다.

키 확인은 모델 목록 조회입니다. 호환 목록은 공식 모델 문서 기준(2026-10-30, backend/model_support.py)이며 계정별 추론 권한·잔여 사용 한도·모든 입력의 성공까지 보장하지 않습니다. 실행 오류는 화면에 표시됩니다. 키 연결 자체는 생성 호출을 하지 않습니다. **실행**부터 모델 API 사용량이 발생합니다. 키가 없으면 기존 예약 취소 과제를 **모의 실행**으로 확인할 수 있습니다. 새 자원 배정 과제는 API 모드에서 실행합니다. 연결 실패 시 모의 실행으로 자동 전환하지 않습니다.

## 키와 프롬프트

- 키는 로컬 서버 메모리에만 보관합니다. 연결 해제·서버 종료 후 다시 입력해야 합니다.
- 키 입력칸은 제출 즉시 비웁니다. 브라우저 저장소, 설정 파일, 실행 기록, 생성 코드, 자식 실행 환경에 키를 넣지 않습니다.
- OpenAI 통신은 서버에서 `https://api.openai.com/v1/`로만 수행합니다. 인증 오류의 원문은 화면이나 기록으로 전달하지 않습니다.
- 프롬프트는 공백·줄바꿈까지 원문 그대로 각 API 호출의 별도 developer 메시지로 전달합니다. 구조화 응답·실행 범위를 지정하는 공통 지침과 프로젝트 상태는 별도 메시지로 전달합니다.
- 감시자 3개는 같은 상태 스냅샷을 각자의 프롬프트로 검토합니다. 계획 단계부터 관찰하며, 질문은 다른 감시자를 기다리지 않고 등록됩니다. 최종 완료 전에는 현재 코드에 대한 검토 결과를 확인합니다.
- 웹 화면의 **감시 의견 원문과 전달 상태**에서 의견별로 메인이 받은 코드 버전, 연결된 질문과 담당자 답, 기본 예약 과제에서 해당 답의 검사가 통과한 버전을 확인할 수 있습니다. 질문 칸 밖의 의견에도 답변을 연결할 수 있습니다.
- 인간 답변과 추가 조언은 다음 메인·감시 호출에 포함됩니다. 질문 key로 중복을 합치고, 영향받는 작업을 표시합니다.

## 실제 실행과 검증 범위

실제 모드에서는 모델이 계획·소스 코드·질문을 생성합니다. 공개 과제만 전달하고 숨겨진 정책·평가 입력·정답은 모델 입력에서 제외합니다. 상단 **규칙** 버튼은 진행자가 보는 채점 기준이며 에이전트에 자동 전달하지 않습니다.

새 인간 답변 없이 자동으로 코드를 6회 작성·수정하면 일시 대기합니다. 인간 답변 반영은 이 횟수에 포함하지 않으며, 새 답변이 있으면 횟수를 초기화합니다. 대기 중에도 답변을 입력할 수 있고 **계속하기**로 기존 코드·질문·답변을 유지하며 재개합니다. 한 번의 응답 제한 시간은 120초입니다. 중단하면 이후 결과를 반영하지 않습니다. 이미 전송된 API 호출의 과금까지 취소하는 기능은 아닙니다.

생성 코드의 문법, 과제별 `can_cancel(now, booked_at, starts_at)` 또는 `simulate(initial_state, events)` 함수, 모델이 제안한 최대 10개 자체 검증을 확인합니다. 자체 검증과 최종 벤치마크는 별개입니다. 자원 배정 자체 검증은 initial_state·events 입력과 기대 객체를 각각 input_json·expected_json 문자열로 전달하며, 정확한 객체 구조까지 비교합니다. 인간 결정 반영 여부는 메인 모델의 반영 보고와 감시 검토로 기록하며, 이를 의미적 정확도 보장으로 표시하지 않습니다. 최종 기능 정확도는 사용자가 실행하는 별도 채점에서 확인합니다.

모델 코드 실행은 macOS `sandbox-exec`로 분리합니다. 시스템 Python 라이브러리·임시 제출 파일만 읽을 수 있고 프로젝트·정답 파일 읽기, 파일 쓰기, 네트워크, 자식 프로세스 생성은 허용하지 않습니다. 환경변수를 비우고 실행 시간·CPU 시간을 제한합니다. 격리 실행에 실패하면 일반 실행으로 우회하지 않습니다. 정답 대조는 신뢰하는 부모 프로세스가 수행합니다.

모의 모드는 고정 규칙·템플릿을 사용하며 자연어 프롬프트를 해석하지 않습니다. 구조화 정책 값을 입력해 기존 흐름과 채점기를 확인하는 용도입니다.

## 저장

- **설정 저장**: 브라우저에 키를 제외한 설정만 저장. 주소·브라우저별 분리.
- `var/runs.sqlite3`: 실행 상태, 질문·답변, 원문 프롬프트, 모델 요청·응답·사용량.
- `var/<실행 ID>/`: 버전별 코드와 수동 채점 결과.
- **실행 기록 / 코드**: 현재 실행 내려받기.
- 서버 재시작 시 미완료 실행은 중단으로 기록합니다. 키를 다시 연결한 뒤 **계속하기**로 재개할 수 있습니다. 이전 버전의 6회 수정 제한으로 실패한 실행도 대기 상태로 복구합니다. 자동 재개하지 않습니다.

기본 예약 취소는 입출력 계약과 짧은 고객 안내문을 제공합니다. 나머지 두 과제는 입출력 계약과 실행 형식을 제공합니다. 추가 정책은 사용자 프롬프트와 해당 실행의 인간 답변으로 전달합니다. 시간대·휴무·마감·예외·오류 처리의 정답 정책은 각 과제의 진행자용 답변 카드와 사이트의 규칙 화면에서 확인합니다. 해당 내용은 에이전트에 자동 전달하지 않습니다. 기존 실행 기록은 유지되므로 변경된 실험은 새 실행으로 시작하세요.

## 파일과 API

```text
web/                        화면
backend/openai_client.py    서버 전용 API 연결·오류 처리
backend/live_schemas.py     모델 응답 형식·공통 지침
backend/live_workflow.py    실제 메인·감시자 실행
backend/isolated*.py        생성 코드 격리 검증·채점
backend/engine.py           상태·기록·모의 실행
backend/server.py           로컬 HTTP API
backend/adapters.py         모의 모델
reservation_benchmark/      예약 취소 100문항·정답·채점기
resource_allocation_benchmark/  자원 배정 150세트·정답·제출 양식·채점기
```

`GET /api/connection`은 연결 상태와 모델 ID만 반환합니다. `POST /api/connection`에 `{key}`를 보내 연결하고, `POST /api/connection/disconnect`로 해제합니다. `POST /api/connection/refresh`로 같은 키의 모델 목록을 갱신합니다(실행 중에는 불가). `POST /api/runs`의 `task_id`는 `cancellation_basic`, `cancellation`(생략 시 기본값), `allocation` 중 하나입니다. 단독 실행 요청은 `architecture: "main-only"`와 `monitors: []`를 사용합니다. 기존 기록에 task_id가 없으면 예약 취소로 해석합니다. `mode`는 `openai` 또는 `mock`입니다. 실제 모드 답변은 `POST /api/runs/{id}/requests/{requestId}/answer`에 `{answer:{text},note}` 형태로 전달합니다. 기록 조회·중단·수동 테스트는 기존 `/api/runs/{id}`, `/stop`, `/test` 경로를 사용합니다. 대기·재시작 중단 상태의 재개는 `POST /api/runs/{id}/resume`입니다.

공식 규격: [Responses 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses), [모델 목록 API](https://developers.openai.com/api/reference/resources/models/methods/list), [모델 ID](https://developers.openai.com/api/docs/models).

## 검증

```sh
python3 -B -m unittest discover -s tests -v
(cd reservation_benchmark && python3 -B -m unittest discover -s tests -v)
python3 -B resource_allocation_benchmark/evaluator/validate_dataset.py
node --check web/app.js
node --test tests/web-runtime.test.cjs
```

자동 테스트는 대체 API 응답을 사용하며 실제 API 호출·과금은 없습니다. 실제 키의 인증·모델 접근 여부는 사이트의 연결·실행 시 확인합니다.

## 오류 후 이어가기

생성 코드의 문법·외부 패키지·자체 검증 오류는 실패한 검증 결과로 에이전트에 반환합니다. 네트워크·API·감시 응답 오류는 일시 정지하며 대기 질문의 답변 입력은 계속 허용합니다. 기존 버전에서 실패한 실행도 답변을 저장하고 키 연결 후 **계속하기**로 이어갈 수 있습니다. 이전 코드·질문·답변과 오류 기록을 유지하며, 재개 자체는 모델 호출을 다시 시작합니다. 완료·사용자 중단 상태는 답변을 받지 않습니다.

답변 처리 보고는 `applied_decision_ids`(코드 반영 보고)와 `context_decision_ids`(코드 변경이 필요 없는 맥락 확인)로 구분합니다. 맥락 답변을 코드 반영으로 표시하지 않습니다. 누락·알 수 없는 ID·두 목록의 중복이 있으면 구체적 피드백과 함께 최대 2회 재요청하고, 계속 불일치하면 답변을 보존한 채 일시 정지합니다. 재요청도 API 사용량에 포함되고 실행 기록에 남습니다. 분류는 모델 보고이며 의미적 정확도 보장은 아닙니다.

프로젝트 진행 상단에 진행 중/답변 대기/일시 정지/완료/오류를 표시합니다. 활성 호출이 있으면 메인·감시자의 응답 대기를 표시하며, 일시 정지 상태는 자동 진행되지 않음을 명시합니다. 서버 연결이 끊기면 마지막 상태를 진행 중으로 단정하지 않습니다.

## 오류 상세 기록

프로젝트 진행의 **오류 상세**에서 최근 10개 오류의 시간·에이전트·모델·작업·검사 단계·코드 버전·경과 시간·예상 조건과 실제 값·응답 ID·실패 응답·발생 파일/행을 확인합니다. 실행 기록 JSON에는 전체 `diagnostics`와 연결된 `calls`가 저장됩니다. 모델 응답은 검증 전에 저장하므로 실패한 질문 목록도 확인할 수 있습니다. API 오류에는 HTTP 상태·오류 코드·요청 ID를 남기며, 불완전/비정상 JSON 응답도 민감 정보를 가려 보존합니다. 인증 헤더·스택 지역 변수·HTTP 오류 본문 메시지는 수집하지 않습니다. 키 형태와 인증 필드는 마스킹합니다. 과거에 저장하지 않은 응답은 복원하지 않으며 화면에 이를 표시합니다.
