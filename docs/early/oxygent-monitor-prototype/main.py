"""작업자 1 + 감시 역할 3. OxyGent 호출 구조만 사용하며 모델 호출은 없다."""

import argparse
import asyncio
import copy
import json
import math
from pathlib import Path
from uuid import uuid4

from oxygent import MAS, Config, OxyRequest, OxyState, oxy


ROOT = Path(__file__).resolve().parent
PERSONAS = {
    "requirements": "요구사항 분석가: 명세에 없는 정책만 인간에게 질문한다.",
    "verification": "검증 엔지니어: 확정된 정책과 구현을 비교하고 오류는 자동 수정시킨다.",
    "impact": "변경 영향 분석가: 답변의 버전·내용과 알림 동작까지 확인한다.",
}


def validate_policy(policy):
    if not isinstance(policy, dict) or set(policy) != {"hours", "inclusive"}:
        raise ValueError("답변에는 hours와 inclusive가 필요합니다.")
    if type(policy["hours"]) is not int or not 0 <= policy["hours"] <= 8760:
        raise ValueError("취소 기준 시간은 0~8760 사이 정수여야 합니다.")
    if type(policy["inclusive"]) is not bool:
        raise ValueError("경계값 포함 여부는 참/거짓이어야 합니다.")
    return copy.deepcopy(policy)


def can_cancel(implementation, seconds_before, *, owner=True, cancelled=False):
    """프로토타입이 실제로 실행하는 예약 취소 기능. 입력 단위는 초."""
    if not math.isfinite(seconds_before) or cancelled:
        return False
    if implementation["owner_only"] and not owner:
        return False
    cutoff = implementation["hours"] * 3600
    return (seconds_before >= cutoff if implementation["inclusive"]
            else seconds_before > cutoff)


def should_notify(implementation, *, cancelled):
    return not (cancelled and implementation["suppress_cancelled"])


def check(name, expected, actual):
    return {"name": name, "expected": expected, "actual": actual,
            "passed": expected == actual}


def verdict(role, decision, reason, tests=None):
    return {"role": role, "decision": decision, "reason": reason,
            "tests": tests or []}


async def requirements(request: OxyRequest):
    snapshot = request.arguments["snapshot"]
    if snapshot["policy"] is None:
        return verdict("requirements", "ask_human",
                       "문서에 취소 마감 시간과 경계값 포함 여부가 없습니다.")
    return verdict("requirements", "pass",
                   f"정책 출처: {snapshot['source']}. 추가 질문 없이 진행합니다.")


async def verification(request: OxyRequest):
    s = request.arguments["snapshot"]
    if s["policy"] is None:
        return verdict("verification", "wait", "정책이 확정된 뒤 검증합니다.")
    p, impl = s["policy"], s["implementation"]
    cutoff = p["hours"] * 3600
    tests = [
        check("마감 1시간 전", True, can_cancel(impl, cutoff + 3600)),
        check("마감 1초 전", True, can_cancel(impl, cutoff + 1)),
        check("정확한 마감 시각", p["inclusive"], can_cancel(impl, cutoff)),
        check("마감 1초 후", False, can_cancel(impl, cutoff - 1)),
        check("마감 1시간 후", False, can_cancel(impl, cutoff - 3600)),
        check("다른 사용자의 예약", False, can_cancel(impl, cutoff + 3600, owner=False)),
        check("이미 취소된 예약", False, can_cancel(impl, cutoff + 3600, cancelled=True)),
    ]
    passed = all(t["passed"] for t in tests)
    return verdict("verification", "pass" if passed else "revise",
                   "취소 기능 검증 통과." if passed else "확정된 명세와 불일치. 인간 질문 없이 수정합니다.", tests)


async def impact(request: OxyRequest):
    s = request.arguments["snapshot"]
    if s["policy"] is None:
        return verdict("impact", "wait", "정책 결정 후 취소·알림의 영향을 확인합니다.")
    p, impl = s["policy"], s["implementation"]
    tests = [
        check("정책 버전 반영", s["version"], impl["version"]),
        check("정책 내용 반영", p, {k: impl[k] for k in p}),
        check("취소된 예약의 알림 차단", False, should_notify(impl, cancelled=True)),
        check("정상 예약의 알림 유지", True, should_notify(impl, cancelled=False)),
    ]
    passed = all(t["passed"] for t in tests)
    return verdict("impact", "pass" if passed else "revise",
                   "정책 반영 및 알림 영향 검증 통과." if passed else "정책 반영 또는 알림 동작을 수정해야 합니다.", tests)


async def worker(request: OxyRequest):
    s = copy.deepcopy(request.arguments["snapshot"])
    s["implementation"] = None
    if s["policy"] is not None:
        s["implementation"] = {
            **s["policy"], "version": s["version"],
            "owner_only": True, "suppress_cancelled": True,
        }
        if s.get("inject_bug"):
            # 오류 감지 경로를 재현하기 위한 의도적인 실험 조건.
            s["implementation"]["inclusive"] = not s["policy"]["inclusive"]
    parallel_id = uuid4().hex
    responses = await asyncio.gather(*(
        request.call(callee=name, arguments={"snapshot": copy.deepcopy(s)},
                     parallel_id=parallel_id)
        for name in PERSONAS
    ))
    for response in responses:
        if response.state != OxyState.COMPLETED:
            raise RuntimeError(f"감시 실행 실패: {response.output}")
    return {"snapshot": s, "reviews": [r.output for r in responses],
            "trace_id": request.current_trace_id}


def build_mas():
    # 외부 DB, 모델, 웹 서버 없이 메모리 저장소만 사용한다.
    Config.set_module_config("es", {})
    Config.set_module_config("redis", {})
    Config.set_module_config("vearch", {})
    Config.set_storage_es_engine("MemoryEs")
    Config.set_token_tracking_enabled(False)
    Config.set_module_config("live_prompt", "is_active", False)
    Config.set_module_config("log", "level_terminal", "ERROR")
    Config.set_module_config("log", "path", str(ROOT / "runs" / "oxygent.log"))
    Config.set_module_config("cache", "save_dir", str(ROOT / "runs" / "cache"))
    return MAS(name="monitor_prototype", oxy_space=[
        oxy.Workflow(name="worker", is_master=True, retries=1,
                     permitted_oxy=list(PERSONAS), func_workflow=worker),
        *[oxy.Workflow(name=name, desc=PERSONAS[name], retries=1, func_workflow=fn)
          for name, fn in [("requirements", requirements),
                           ("verification", verification), ("impact", impact)]],
    ])


async def run(mas, case, answer, on_step=lambda step: None):
    """인간 응답은 호출자가 주입한다. CLI 입력 또는 테스트용 고정 답변."""
    if case not in {"missing", "documented", "bug"}:
        raise ValueError("알 수 없는 과제입니다.")
    s = {"policy": None if case == "missing" else {"hours": 24, "inclusive": True},
         "source": "missing" if case == "missing" else "document",
         "version": 0 if case == "missing" else 1, "inject_bug": case == "bug"}
    result = {"mode": "offline_rules", "case": case, "personas": PERSONAS,
              "steps": [], "human_answers": [], "human_questions": 0, "repairs": 0}
    for _ in range(3):
        response = await mas.chat_with_agent(payload={
            "callee": "worker", "snapshot": s,
            "is_save_history": False, "is_async_storage": False,
        })
        if response.state != OxyState.COMPLETED:
            raise RuntimeError(f"작업 실행 실패: {response.output}")
        step = response.output
        result["steps"].append(step)
        on_step(step)
        decisions = {r["decision"] for r in step["reviews"]}
        if "ask_human" in decisions:
            result["human_questions"] += 1
            s["policy"] = validate_policy(await answer())
            s["source"], s["version"] = "human", s["version"] + 1
            result["human_answers"].append({"version": s["version"], **s["policy"]})
        elif "revise" in decisions:
            if result["repairs"]:
                break
            result["repairs"] += 1
            s["inject_bug"] = False
        elif decisions == {"pass"}:
            result["status"] = "completed"
            break
        else:
            break
    result.setdefault("status", "failed")
    final = result["steps"][-1]
    tests = [t for r in final["reviews"] for t in r["tests"]]
    result["implementation"] = final["snapshot"]["implementation"]
    result["metrics"] = {
        "checks_passed": sum(t["passed"] for t in tests), "checks_total": len(tests),
        "worker_rounds": len(result["steps"]),
        "human_questions": result["human_questions"], "auto_repairs": result["repairs"],
    }
    return result


def show_step(step):
    print("\n[작업자] 정책 작성 → 감시 역할 3개 병렬 호출")
    labels = {"ask_human": "질문 필요", "wait": "검증 대기", "pass": "통과", "revise": "수정 필요"}
    for review in step["reviews"]:
        title = PERSONAS[review["role"]].split(":")[0]
        print(f"  {title} [{labels[review['decision']]}] {review['reason']}")


async def ask_human():
    print("\n[인간 판단] 예약 시작 몇 시간 전까지 취소할 수 있나요?")
    while True:
        try:
            hours = int(input("시간 (예: 24): "))
            boundary = input("정확히 그 시각에도 취소를 허용하나요? (y/n): ").strip().lower()
            if boundary not in {"y", "n"}:
                raise ValueError("y 또는 n을 입력해주세요.")
            return validate_policy({"hours": hours, "inclusive": boundary == "y"})
        except ValueError as exc:
            print(f"입력을 확인해주세요: {exc}")


async def main():
    parser = argparse.ArgumentParser(description="OxyGent 최소 감시 프로토타입 — API 없음")
    parser.add_argument("--case", choices=["missing", "documented", "bug"], default="missing")
    parser.add_argument("--demo", action="store_true", help="실제 입력 대신 예시 답변(24시간, 경계 포함)")
    args = parser.parse_args()
    print("규칙 기반 모의 실행입니다. 모델의 판단 성능을 측정하지 않습니다.")

    async def demo_answer():
        print("\n[예시 답변 자동 입력 — 인간 응답 아님] 24시간 전까지, 정확히 24시간도 허용")
        return {"hours": 24, "inclusive": True}

    async with build_mas() as mas:
        result = await run(mas, args.case, demo_answer if args.demo else ask_human, show_step)
    result["answer_mode"] = "scripted" if args.demo else "interactive"
    output = ROOT / "runs" / f"{args.case}-{uuid4().hex[:12]}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = result["metrics"]
    print(f"\n결과: {result['status']} | 검증 {metrics['checks_passed']}/{metrics['checks_total']}"
          f" | 질문 {metrics['human_questions']}회 | 자동 수정 {metrics['auto_repairs']}회")
    print(f"기록: {output}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except (KeyboardInterrupt, EOFError):
        print("\n실행을 종료했습니다.")
        raise SystemExit(130)
