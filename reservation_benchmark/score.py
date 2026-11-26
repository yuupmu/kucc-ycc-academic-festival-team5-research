"""신뢰하는 로컬 Python 제출을 고정 100문항으로 채점합니다."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASIC_CATEGORIES = ('평일 마감', '마감 경계', '예약 직후 유예', '시작과 유예 우선순위')


def load_submission(path):
    spec = importlib.util.spec_from_file_location("benchmark_submission", str(path))
    if spec is None or spec.loader is None:
        raise ValueError("Python 제출 파일을 읽을 수 없습니다.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, "can_cancel", None)
    if not callable(function):
        raise ValueError("can_cancel(now, booked_at, starts_at) 함수가 필요합니다.")
    return function


def load_cases(basic=False):
    dataset = json.loads((ROOT / "evaluator/cases.json").read_text())
    key = json.loads((ROOT / "evaluator/answer_key.json").read_text())
    policy_hash = hashlib.sha256((ROOT / "evaluator/policy.json").read_bytes()).hexdigest()
    if not dataset["policy_sha256"] == key["policy_sha256"] == policy_hash:
        raise ValueError("정책과 테스트 버전이 다릅니다. 사례와 정답을 함께 갱신하세요.")
    cases, answers = dataset["cases"], key["answers"]
    ids = [case["id"] for case in cases]
    if len(ids) != 100 or len(set(ids)) != 100 or set(ids) != set(answers):
        raise ValueError("중복/누락 없이 100문항과 정답이 일치해야 합니다.")
    if basic:
        cases = [case for case in cases if case["category"] in BASIC_CATEGORIES]
        if any(sum(c["category"] == name for c in cases) != 10 for name in BASIC_CATEGORIES):
            raise ValueError("기본 예약 취소는 4개 유형별로 10문항을 사용합니다.")
    version = dataset["benchmark_version"] + ("-basic.1" if basic else "")
    return cases, answers, version, policy_hash


def grade_cases(function, cases, answers, version, policy_hash):
    rows, categories = [], {}
    label_scores = {"allow": {"correct": 0, "total": 0}, "deny": {"correct": 0, "total": 0}}
    for case in cases:
        expected = answers[case["id"]]["allowed"]
        result, error = None, None
        try:
            result = function(case["now"], case["booked_at"], case["starts_at"])
            if type(result) is not bool:
                raise TypeError("반환값은 bool이어야 합니다.")
        except Exception as exc:
            result = None
            error = f"{type(exc).__name__}: {exc}"
        passed = error is None and result is expected
        count = categories.setdefault(case["category"], {"correct": 0, "total": 0})
        count["correct"] += int(passed)
        count["total"] += 1
        label = label_scores["allow" if expected else "deny"]
        label["correct"] += int(passed)
        label["total"] += 1
        rows.append({"id": case["id"], "category": case["category"], "expected": expected,
                     "actual": result, "passed": passed, "error": error})
    score = sum(row["passed"] for row in rows)
    return {"benchmark_version": version, "policy_sha256": policy_hash,
            "score": score, "total": len(rows), "accuracy_percent": round(100 * score / len(rows), 2),
            "errors": sum(row["error"] is not None for row in rows),
            "categories": categories, "labels": label_scores, "results": rows}


def grade(function):
    return grade_cases(function, *load_cases())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = grade(load_submission(args.submission.resolve()))
    print(f"총점: {result['score']}/{result['total']} | 실행 오류: {result['errors']}개")
    for category, count in result["categories"].items():
        print(f"  {category}: {count['correct']}/{count['total']}")
    for label, count in result["labels"].items():
        print(f"  정답 {label}: {count['correct']}/{count['total']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(f"상세 결과: {args.output}")


if __name__ == "__main__":
    main()
