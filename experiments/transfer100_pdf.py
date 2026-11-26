"""Create the printable report from completed, frozen measurements."""
import json
from pathlib import Path

from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import HorizontalBarChart
from reportlab.graphics import renderPDF, renderSVG
from reportlab.lib import colors

from experiments import transfer100_study as study
from experiments.pipeline100.pdf_layout import Report, M, WIDTH, HEIGHT, FONT

ROOT = study.STUDY


def read(path):
    return json.loads(path.read_text())


def build():
    data = read(ROOT/'research/observations.json')
    findings = read(ROOT/'research/findings.json')
    names = read(ROOT/'evaluator/tasks.json')
    questions = read(ROOT/'evaluator/cases.json')
    summary = {r['arm']: r for r in data['summary']}
    records = {(r['task'], r['arm']): r for r in data['by_project']}
    out = ROOT/'output/pdf'
    out.mkdir(parents=True, exist_ok=True)
    path = out/'새유형_100문항_파이프라인_비교보고서.pdf'
    doc = Report(path)
    doc.c.setTitle('새 유형 100문항 - 인간 개입 파이프라인 21조건 비교')
    selected = ['solo','self-fidelity-3','multi-fidelity-3']
    labels = ['메인 단독','현재 자체 검토 3회','현재 감시자 3회']
    best = max(study.ARMS, key=lambda a: summary[a]['correct'])

    doc.page('새 유형 100문항 비교', '결과 요약')
    doc.para(findings['lead'], size=12, leading=19)
    doc.note('5개 독립 함수 × 입력 20개 = 100문항. 21조건 × 함수 5개 = 최종 제출 105개. 같은 Qwen3.5-4B 모델과 시드 263을 사용했다.')
    drawing = Drawing(WIDTH-2*M, 155)
    bar = HorizontalBarChart()
    bar.x = 130; bar.y = 25; bar.width = 335; bar.height = 112
    bar.data = [[summary[a]['correct'] for a in selected]]
    bar.categoryAxis.categoryNames = labels
    bar.categoryAxis.labels.fontName = FONT; bar.categoryAxis.labels.fontSize = 9
    bar.valueAxis.valueMin = 0; bar.valueAxis.valueMax = 100; bar.valueAxis.valueStep = 20
    bar.valueAxis.labels.fontName = FONT; bar.valueAxis.labels.fontSize = 9
    bar.bars[0].fillColor = colors.HexColor('#006A65')
    bar.bars[0].strokeColor = None
    bar.barLabelFormat = '%d'; bar.barLabels.fontName = FONT; bar.barLabels.fontSize = 10
    drawing.add(bar)
    renderPDF.draw(drawing, doc.c, M, HEIGHT-doc.y-155)
    renderSVG.drawToFile(drawing, str(out/'주요조건_정답수.svg'))
    doc.y += 175
    doc.table(['과제 / 20문항','단독','현재 자체','현재 다중','P2'], [
        [names[t]['name'], *[records[t,a]['correct'] for a in [*selected,'p2']]] for t in study.TASKS], [2.2,1,1,1,1], size=10, row=25)
    doc.para(f"전체 조건 중 최고 점수는 {study.NAMES[best]}의 {summary[best]['correct']}/100이다. 총점은 표본 내 관찰값이며, 독립 프로젝트 100개에서의 성능을 뜻하지 않는다.", size=10)
    doc.para('기존 구조를 그대로 비교했다. 평가 결과를 본 뒤 모델에 재수정을 요청하거나, 좋은 회차를 골라 최종 점수로 사용하지 않았다.',size=10)
    doc.end()

    doc.page('비교 구조와 인간 개입', '실험 설계')
    doc.para('이번 과제는 제목 정리, 확장자 추출, 식별코드 가림, 업로드 크기, 인쇄 영역이다. 날짜·일정·배정·상태 전이를 없애고 제한된 문자열과 작은 정수의 순수 함수로 설계했다.')
    for title, text in [
        ('① 메인 단독', '공개 명세 → 공통 초안 → 최종 제출'),
        ('② 메인 자체 검토', '초안 → 메인이 부족한 정책 질문 → 담당자 자연어 답 → 메인 수정'),
        ('③ 메인 + 감시자 A·B·C', '초안 → 관점별 독립 검토 → 최대 3개 질문 묶음 → 담당자 자연어 답 → 메인 수정'),
    ]:
        doc.h(title); doc.note(text)
    doc.h('3회차에서는 실제 자기 코드를 다시 검토한다')
    doc.para('질문 1 → 답변 1 → 코드 1 → 질문 2 → 답변 2 → 코드 2 → 질문 3 → 답변 3 → 최종 코드. 같은 첫 질문을 사용하는 작성 조건에는 같은 첫 회신을 제공했다. 후속 질문은 직전 코드에 따라 달라질 수 있다.',size=10)
    doc.para('사용자의 위임에 따라 연구 진행자가 담당자를 대리했다. 추론 전에 고정한 정책 카드 중 질문받은 내용만 자연어로 답했다. 답변 선택 이유와 질문 원문을 모두 저장했다. 실제 사용자가 직접 응답한 횟수는 0회다.',size=10)
    doc.h('모델과 평가자의 정보 경계')
    doc.para('모델: 공개 명세, 해당 조건의 코드, 실제 질문·회신. 평가자: 모든 최종 제출을 고정한 뒤 숨겨진 100문항과 기대값으로 평가. 1·2회차 사본의 점수도 실험 종료 후 산출했다.',size=10)
    doc.para('비교 범위는 인간 개입 목표 확정 뒤의 재사용 가능한 P1~P4, 적용 보완, a/b 작성기, 이전·현재 3회차 조건이다. 중간 채점 노출 조건과 예약 전용 후보 선택 A/B/C/D는 제외했다.',size=9)
    doc.end()

    doc.page('전체 21조건의 결과', '정답과 비용')
    doc.para('토큰은 입력+출력의 합이다. 조건별 수치에는 공유한 요청의 실제 사용량도 포함해, 해당 조건을 단독 실행할 때의 비용으로 비교한다. 보류·오류는 0점이다.',size=10)
    doc.table(['조건','정답','오답','보류·오류','질문','토큰'], [
        [study.NAMES[a],summary[a]['correct'],summary[a]['wrong'],summary[a]['unanswered'],summary[a]['questions'],f"{summary[a]['total_tokens']:,}"] for a in study.ARMS],
        [4.2,0.8,0.8,1.1,0.8,1.7],size=8.7,row=21,accent=[0,19,20])
    doc.para('P1: 공통 관점 / P2: 역할 분담 / P3: 상황과 두 결과 / P4: 질문 정리와 답·코드 줄 인용 / a: 가능한 규칙을 구분하는 질문 / b: 받은 답을 실제 코드에 옮기는 방식.',size=9,leading=14)
    doc.para('일반 코드, 자유 조건식, 입력 영역은 작성 방식의 차이다. 현재 구조는 자연어 답과 해당 입력 영역의 선택을 연결하고, 일반 코드 경로에서는 질문·회신 문맥을 추가한다.',size=9,leading=14)
    doc.end()

    doc.page('유형별로 무엇이 달라졌나', '세부 유형 25개')
    doc.para('각 칸은 해당 유형에서 맞힌 문항 수다. 비교 순서는 단독 / 현재 자체 검토 3회 / 현재 감시자 3회 / P2이다. 21조건 전체 유형표는 research/by-type.csv에 있다.',size=10)
    body=[]
    for task in study.TASKS:
        for category in dict.fromkeys(r['category'] for r in questions if r['task']==task):
            ids={r['id'] for r in questions if (r['task'],r['category'])==(task,category)}
            body.append([names[task]['name']+' / '+category,len(ids),*[
                sum(c['status']=='correct' for c in data['cases'] if c['id'] in ids and c['arm']==a) for a in [*selected,'p2']]])
    doc.table(['과제 / 유형','문항','단독','자체','다중','P2'],body,[4.6,0.8,0.8,0.8,0.8,0.8],size=8.5,row=20)
    doc.para('같은 함수의 입력은 서로 독립적인 개발 프로젝트가 아니다. 유형별 점수 차이는 사례 진단에 사용하고 일반화 성능의 통계적 우위로 확대하지 않는다.',size=9,leading=14)
    doc.end()

    doc.page('반복 회차와 실패 위치', '과정 분석')
    cycle_rows=[]
    for arm in study.CYCLES:
        for n in (1,2,3):
            rs=[c['metrics'] for c in data['cycles'] if c['metrics']['arm']==arm and c['metrics']['cycle']==n]
            cycle_rows.append([study.NAMES[arm],n,sum(r['correct'] for r in rs),sum(r['questions'] for r in rs),f"{sum(r['total_tokens'] for r in rs):,}"])
    doc.table(['조건','회차','정답 /100','누적 질문','누적 토큰'],cycle_rows,[3.4,0.7,1.1,1.1,1.6],size=9,row=20)
    doc.h('정책을 받았는지와 구현했는지를 구분')
    doc.table(['조건','공개 요구 실패','답 확보 후 실패','답 미수신 오답','답 미수신 보류'],[
        [label,summary[a]['public_wrong']+summary[a]['public_defer'],summary[a]['known_wrong']+summary[a]['known_defer'],summary[a]['missing_wrong'],summary[a]['missing_defer']]
        for a,label in zip(selected,labels)],[2.4,1.3,1.3,1.3,1.3],size=8.5,row=24)
    doc.para(findings['cycles'],size=10)
    doc.para('필요 정책은 사전에 표시한 문항별 의존성과 실제 회신으로 판정했다. 인쇄 두 치수가 모두 초과할 때는 어느 한 축의 상한만 알아도 거부 근거가 충분하다고 인정한다. 자연어 의미의 완전한 증명을 뜻하지 않는다.',size=9,leading=14)
    doc.end()

    for page, stories in enumerate([findings['stories'][:3],findings['stories'][3:]],1):
        doc.page('질문·답·코드를 연결한 사례', f'사례 분석 {page}/2')
        for story in stories:
            doc.h(story['title'])
            doc.para(story['text'],size=10,leading=16,gap=7)
            doc.para('근거: '+story['source'],size=8,leading=12,gap=15)
        doc.end()

    doc.page('재현 기록과 해석 범위', '연구 기록')
    physical=data['physical']
    doc.h('전체 실소모')
    doc.para(f"중복 제거한 고유 모델 호출 {physical['unique_calls']:,}회. 입력 {physical['prompt_tokens']:,}토큰, 출력 {physical['completion_tokens']:,}토큰, 합계 {physical['total_tokens']:,}토큰. 기록된 응답 시간의 합은 {physical['seconds']/60:.1f}분이다.")
    doc.para('응답 없이 끊긴 전송은 사용량을 알 수 없어 합계에 포함하지 못했다. 전체 경과 시간에는 대리 답변, 개발, 대기 시간도 들어간다. 조건별 토큰 총합과 고유 호출의 실소모는 공유 요청 때문에 다르다.',size=10)
    doc.h('변경과 장애 기록')
    doc.para(findings['infrastructure'],size=10)
    doc.h('공개할 때 함께 제시할 한계')
    doc.para('시드 1개, 독립 과제 5개다. 질문 기회와 총 토큰 예산은 구조마다 다르다. 담당자 답변은 고정 정책 카드에 기반한 연구자의 대리 응답이다. 이전 예약·배정 표본과 난이도가 달라 총점 차이를 구조 개선량으로 비교할 수 없다.',size=10)
    doc.para('최종 3회차를 사용했으며, 중간 최고 점수로 교체하지 않았다. 입력 영역 방식이 일반 코드로 전환된 경우와 보류·작성 오류도 성능에 포함했다. 전 역할이 같은 로컬 모델을 사용하므로 서로 다른 모델 조합의 우위를 검증한 실험은 아니다.',size=10)
    doc.h('상세 자료 위치')
    for text in ['README.md: 전체 분석과 연결된 원기록', 'problem-set.md: 100개 입력·기대값·정책 의존성', 'research/questions.md: 실제 질문·담당자 회신·선택 이유', 'research/items.csv: 2,100개 최종 판정과 실행 줄', 'research/summary.csv / cycles.csv: 전체 비용과 회차별 변화', 'research/paired-writers.csv / question-routing.csv: 작성 방식·질문 전달', 'submissions-manifest.json: 최종 제출과 원기록 해시']:
        doc.para(text,size=9,leading=14,gap=4)
    doc.end();doc.save()
    print(path)


if __name__=='__main__':
    build()
