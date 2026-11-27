# 학술제 실험 원자료 이용 안내

각 조건에서 감시자가 무엇을 물었는지, 담당자가 어떤 정책을 답했는지, 작성 전후 코드와 실제 반환값이 어떻게 달라졌는지를 대조할 수 있다. 시드와 입력이 같은 기록을 재사용한 경우에는 해당 실험의 설계 문서와 호출 해시를 함께 확인한다.

| 연구 질문 | 시작 자료 | 이어서 확인할 자료 |
|---|---|---|
| 예약·문의 100문항에서 어느 단계가 점수를 갈랐나? | [설계와 보고서](../../experiments/pipeline100/README.md) | [회차별 기록](../../experiments/pipeline100/runs) · [문항별 분석](../../experiments/pipeline100/research) |
| 세 모델과 감시 구성에 따라 점수·비용이 달라졌나? | [조건별 비교표](../../experiments/family-reply-delta-20261126/README.md) | [전이 실험](../../var/family-100-v1) · [예약 실험](../../var/reservation-family-v1) |
| 답변을 반대로 주면 딱 그 입력에서 결과가 달라지나? | [고정한 초안·문답](../../experiments/answer-flip-20261126/frozen) | [제출 코드](../../experiments/answer-flip-20261126/runs) · [사전 검사와 사후 반례](../../experiments/answer-flip-20261126/evaluator) |
| 미응답 한 항목만 보류하고 다시 묻는가? | [처음 보낸 질문과 결정 항목](../../experiments/decision-ledger-20261126/agendas) | [직접 회신과 후속 회신의 제출 상태](../../experiments/ledger-receipts-20261126/runs) · [결과와 토큰](../../experiments/ledger-receipts-20261126/results.json) |

후기 실험의 담당자는 미리 정한 정책을 가진 대리 응답자였다. 점수는 해당 실행에서 사용한 기준으로 읽어야 한다. 예를 들어 등호 처리에 답을 받지 않은 업로드 제출은 정확히 상한인 입력을 보류해야 ‘실제로 받은 정책’ 기준에서 정답이다. 기존 공식 채점은 같은 입력을 허용으로 채점한다.

## 공개 범위와 무결성

이번 추가 공개 목록은 [inventory.tsv](inventory.tsv)에 있다. 한 행은 한 파일 또는 저장소 내부 상대 링크이며, 해시는 공개한 내용의 SHA-256이다. 모델에 보낸 실험 프롬프트와 생성 응답, 정책 카드, 시드, 제출물, 실행 시간, 토큰, 채점 결과를 포함한다. 벤치마크의 가상 사용자 식별자는 문항 안에서 같은 대상을 대조하는 데 사용한다.

운영 로그·서버 시작 기록·실행 DB·모델 가중치는 배포 대상에서 제외했다. 일부 초안 출처는 저장소 상대 경로로 바꿨고 일정 배정 실행 상태는 연구에 쓰는 필드만 남겼다. 이 파일의 공개본 해시는 로컬 원본과 다를 수 있다. [변환한 파일 목록](transformed.txt)

## 제출 후 채점 재현

다음 명령은 macOS에서 업로드·환풍기 제출을 임시 사본에서 다시 채점한다. 기존 평가기는 결과 파일이 있으면 메모리의 튜플과 JSON 배열을 직접 비교하기 때문에, 사본에서만 기존 결과를 별도 이름으로 보존한 뒤 두 JSON의 값을 대조한다. 모델을 다시 호출하지 않는다.

```sh
replay_dir=$(mktemp -d)
git archive HEAD | tar -x -C "$replay_dir"
(
  cd "$replay_dir" || exit 1
  experiment=experiments/ledger-receipts-20261126
  mv "$experiment/results.json" "$experiment/expected.json" &&
  python3 -B "$experiment/assess.py" &&
  python3 -c 'import json,sys; a,b=(json.load(open(p)) for p in sys.argv[1:]); assert a==b; print("공개 결과와 일치합니다.")' "$experiment/expected.json" "$experiment/results.json"
)
```
