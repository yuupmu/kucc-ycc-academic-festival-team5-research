"""Build readable report tables from frozen observations; add source-level findings separately."""
import csv
from collections import Counter
from pathlib import Path

from experiments import transfer100_study as study
from experiments.local_transport import read

ROOT=study.STUDY

def table(headers,rows):
    return ['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|',*[
        '| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in row)+' |' for row in rows],'']

def number(value):
    return f'{value:,}'

def write():
    data=read(ROOT/'research/observations.json')
    names=read(ROOT/'evaluator/tasks.json')
    summary={r['arm']:r for r in data['summary']}
    cases=read(ROOT/'evaluator/cases.json')
    latest=summary['multi-fidelity-3']; self_current=summary['self-fidelity-3']; solo=summary['solo']
    lines=['# 새 유형 100문항에서 인간 개입 파이프라인 21조건 비교','',
        f"새 과제 5개의 100문항에서 메인 단독은 **{solo['correct']}/100**, 현재 메인 자체 검토 3회차는 **{self_current['correct']}/100**, 현재 감시자 A·B·C 3회차는 **{latest['correct']}/100**이었다. 같은 모델과 시드로 21조건, 최종 프로그램 105개를 고정한 뒤 채점했다.",
        '',
        '공개 명세가 충분한 부분과 담당자에게 물어야 하는 정책을 구분했다. 각 과제의 초안은 공유했고, 같은 첫 질문을 사용하는 작성 방식에는 같은 회신을 제공했다. 반복 조건은 실제 직전 코드에서 다음 질문을 생성했다. 중간 채점 결과는 모델에 전달하지 않았다. [설계와 비교 범위](PROTOCOL.md) · [고정한 조건](design.json) · [최종 제출 식별값](submissions-manifest.json)','',
        '## 과제와 표본','',
        '일정이나 상태 전이가 없는 순수 함수 5개다. 문자열 범위를 제한하고 작은 정수 비교를 사용해 계산 부담을 줄였다. 100문항은 100개의 독립 개발 프로젝트가 아니라 **5개 프로그램에 대한 서로 다른 입력 100개**다. 이전 20문항과 난이도가 다르므로 총점의 직접 증감을 구조 개선량으로 해석하지 않는다.']
    lines+=table(['과제','입력 수','세부 유형'],[[names[t]['name'],20,' · '.join(dict.fromkeys(c['category'] for c in cases if c['task']==t))] for t in study.TASKS])
    lines+=['입력·기대값·정책 의존성은 최초 추론 전에 고정했다. 빈 식별코드처럼 결과 길이 보존만으로 답을 알 수 있는 입력은 공개 정보만으로 결정되는 문항으로 취급했다. [전체 문항](problem-set.md) · [원문 평가 데이터](evaluator/cases.json)','',
            '## 전체 파이프라인 결과','',
            '보류와 반환 형식 오류는 점수 0으로 집계했다. 정책 미수신 반환은 필요한 운영 답을 받기 전에 값을 반환한 횟수이며 우연히 맞힌 경우도 포함한다. 토큰 표는 각 조건을 단독 실행할 때 필요한 초안·질문·작성·최종 검토·재시도 호출의 입력+출력 사용량을 합친 것이다. 공유 요청에는 저장된 실제 호출의 사용량을 계상했다. 이번 실행의 중복 제거 실소모는 아래 비용 절에 따로 제시한다.']
    lines+=table(['조건','정답 /100','오답','보류·오류','정책 미수신 반환','질문','누적 토큰'],[
        [study.NAMES[a],summary[a]['correct'],summary[a]['wrong'],summary[a]['unanswered'],summary[a]['unsupported_returns'],
         summary[a]['questions'],number(summary[a]['total_tokens'])] for a in study.ARMS])
    lines+=['[전체 입력·출력 토큰과 호출 횟수](research/summary.csv) · [과제별 결과·작성 형식·실패 기록](research/by-project.csv)','',
            '초기 중간 채점 노출 실험과 예약 전용 후보 선택 A/B/C/D는 이번 규정·과제 범위와 맞지 않아 제외했다. P1은 공통 관점, P2는 역할 분담, P3는 서로 다른 두 결과의 상황 기록, P4는 감시자 C의 질문 정리와 메인의 답·줄 인용이다. a는 두 가능한 규칙을 비교하는 질문 개선, b는 받은 답을 코드로 옮기는 작성 방식의 변경이다.','',
            '## 문제 유형별 비교','']
    focus=['solo','self','p2','p4guard','infer-regions','multi-regions-3','self-fidelity-3','multi-fidelity-3']
    headers=['과제 / 유형','문항 수','단독','자체 1회','P2','P4 보완','a+b 1회','이전 다중 3회','현재 자체 3회','현재 다중 3회']
    body=[]
    for t in study.TASKS:
        for category in dict.fromkeys(c['category'] for c in cases if c['task']==t):
            subset=[c for c in cases if (c['task'],c['category'])==(t,category)]
            body.append([names[t]['name']+' / '+category,len(subset),*[
                sum(c['status']=='correct' for c in data['cases'] if (c['arm'],c['task'],c['category'])==(a,t,category)) for a in focus]])
    lines+=table(headers,body)
    lines+=['표의 각 칸은 해당 유형에서 맞힌 문항 수다. 21조건 전체의 세부 유형과 빈 입력·경계·예외·결합 같은 공통 특성 집계도 제공한다. [21조건 유형별 집계](research/by-type.csv) · [공통 특성별 집계](research/by-skill.csv)','',
            '## 정보 확보와 구현이 끊긴 지점','',
            '문항별로 사전에 표시한 필요한 정책과 실제 회신을 대조했다. 이 지표는 같은 출력이 다른 근거로도 결정될 수 있는 모든 자연어 해석을 증명하는 지표는 아니다. 인쇄 두 축이 모두 초과하면 어느 한 축의 상한만 알아도 거부를 정할 수 있는 대체 근거를 인정했다.']
    lines+=table(['조건','공개 요구 실패','답 확보 후 실패','답 미수신 오답','답 미수신 보류','답 미수신 정답'],[
        [study.NAMES[a],summary[a]['public_wrong']+summary[a]['public_defer'],
         summary[a]['known_wrong']+summary[a]['known_defer'],summary[a]['missing_wrong'],summary[a]['missing_defer'],
         summary[a]['correct_unsupported']] for a in study.ARMS])
    lines+=['[문항별 근거 충족·반환값·실행된 줄](research/observations.json) · [입력별 전체 비교](research/items.csv)','',
            '## 세 회차의 변화','']
    body=[]
    for a in study.CYCLES:
        for n in (1,2,3):
            rs=[c['metrics'] for c in data['cycles'] if c['metrics']['arm']==a and c['metrics']['cycle']==n]
            body.append([study.NAMES[a],n,sum(c['correct'] for c in rs),sum(c['questions'] for c in rs),
                         number(sum(c['total_tokens'] for c in rs)),sum(c['unsupported_returns'] for c in rs)])
    lines+=table(['조건','회차','정답 /100','누적 질문','누적 토큰','정책 미수신 반환'],body)
    lines+=['세 번째 제출을 최종 성능으로 사용했다. 1·2회차는 모두 종료한 뒤 사본으로 평가했다. 회차별 신규 정책과 반복 회신은 질문 기록에서 확인할 수 있다. [모든 질문·담당자 답·선택 근거](research/questions.md) · [회차별 정책 확보](research/question-windows.csv)','',
            '## 질문과 답변의 실제 흐름','',
            '```mermaid','flowchart TD',
            '  P["5개 공개 과제와 과제별 공통 초안"] --> Q["단독 제출 또는 자체·독립 감시 질문"]',
            '  Q --> H["대리 담당자가 질문받은 정책만 자연어로 답함"]',
            '  H --> W["조건별 기존 작성기 또는 개선 작성기"]',
            '  W --> R["실제 코드와 검토 의견 저장"]',
            '  R -->|"반복 조건의 1·2회차"| Q',
            '  R --> F["105개 최종 프로그램 고정"]',
            '  F --> G["연구자만 100문항 평가와 실행 줄 분석"]',
            '```','',
            '담당자는 사전에 고정한 정책 카드에서 실제 질문에 필요한 문장만 선택했고, 코드와 점수에 맞춰 새 규칙을 만들지 않았다. 직접 사용자의 응답은 0회이며 사용자의 위임을 받은 연구 진행자가 대리 응답했다. 질문에 없는 정책은 다음 회차에서 물을 때까지 전달하지 않았다. 같은 질문의 정책은 반복 회신했다.','',
            '## 실험 비용과 재현 범위','']
    physical=data['physical']
    lines +=[f"전체 기록의 고유 모델 호출은 **{physical['unique_calls']}회**, 입력 **{number(physical['prompt_tokens'])}토큰**, 출력 **{number(physical['completion_tokens'])}토큰**, 합계 **{number(physical['total_tokens'])}토큰**이다. 기록된 모델 응답 시간의 합은 {physical['seconds']/60:.1f}분이다. 이는 대리 담당자의 판단·개발·대기 시간을 포함한 전체 경과 시간과 다르다.",
             '',
             '조건별 표에는 공유한 호출의 원래 측정 비용을 각 조건에 넣었다. 전체 실소모에서는 같은 요청을 한 번만 센다. 응답 없이 끊긴 로컬 전송의 사용량은 계측되지 않았으므로 위 합계의 한계로 남긴다. 연결 장애와 서버 로그는 별도로 보관했다. [전송 기록](transport/) · [채점 산출물 식별값](research/manifest.json)','',
             '시드 하나와 5개 과제의 결과다. 총 질문 기회와 토큰 상한을 구조끼리 동일하게 맞춘 비교는 아니다. 이번 표본의 문항 수와 점수만으로 모든 과제에 대한 통계적 우위를 주장할 수 없다. 자유 조건식의 표현 범위, 입력 영역 방식이 일반 코드 경로로 전환되는 경우, 담당자 답을 적용하는 의미 해석의 실패도 결과에 포함했다.','',
             '기존 파이프라인 구현을 고정해 재사용했다. 신규 실행기는 공개 자료만 요청에 넣고, 신규 채점기는 모든 제출의 고정 여부를 확인한 뒤 별도로 실행한다. 핵심 자료는 공개 명세, 운영 정책, 원시 호출, 질문과 회신, 모든 회차 코드, 문항별 실행 줄과 비용이다.','',
             '```sh','python3 -B -m experiments.transfer100_study pending','python3 -B -m experiments.transfer100_execute',
             'python3 -B -m experiments.transfer100_study report','```','']
    position=lines.index('## 과제와 표본')
    lines[position:position]=[
        '[8쪽 PDF 보고서](output/pdf/새유형_100문항_파이프라인_비교보고서.pdf) · [핵심 결과와 코드 원인 분석](analysis.md) · [질문·답변별 개선/퇴행 문항](research/dialogue-effects.csv)', '',
        '현재 감시자는 단독보다 48점, 현재 자체 검토보다 13점 높았다. 전체 최고는 P4 질문+입력 영역의 82점(37,985토큰)이며 현재 감시자는 81점(104,239토큰)이다. 현재 감시자 오답 19개는 필요한 정책 미확보 상태 13개, 이미 알려진 요구 구현 실패 6개로 나뉜다. 최신 구조의 일괄 우위나 답변 반영의 완전 보장을 주장하지 않는다.', '']
    (ROOT/'README.md').write_text('\n'.join(lines))
    problem=['# 연구자용 100문항과 기대값','','모델에는 공개 명세와 실제 질문의 자연어 회신만 전달했다. 이 표는 최종 제출 후의 분석 자료다.','']
    for t in study.TASKS:
        problem += [f"## {names[t]['name']}",'',read(ROOT/'public'/f'{t}.json')['brief'],'']
        problem +=table(['문항','유형','입력','기대값','필요한 정책'],[[r['id'],r['category'],repr(r['args']),repr(r['expected']),', '.join(r['required']) or '공개 정보'] for r in cases if r['task']==t])
    (ROOT/'problem-set.md').write_text('\n'.join(problem))

if __name__=='__main__':
    write()
