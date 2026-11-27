"""Recalculate unanswered decisions from the policy cards, actual replies and sealed behaviors."""
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parents[2] / "experiments/festival-validation-20261127"


def read(path):
    return json.loads(path.read_text())


def recount():
    design = read(STUDY / "design.json")
    counts, details = {}, []
    for run in read(STUDY / "supplement-results.json")["rows"]:
        arm, task, seed = run["arm"], run["task"], run["seed"]
        card = design[task]
        folder = STUDY / "runs" / task / str(seed) / ("self" if arm == "solo" else arm)
        supplement = STUDY / "supplement" / folder.relative_to(STUDY)
        if (supplement / "final.json").exists():
            folder = supplement
        replies = [] if arm == "solo" else [read(p)["reply"] for p in sorted(folder.glob("owner-*.json"))]
        targets = dict(zip(card["policies"], card["targets"]))
        answers = card["by_seed"][design["seeds"].index(seed)]
        counter = counts.setdefault(arm, Counter())
        for index, (policy, target) in enumerate(targets.items()):
            expected = answers[index]
            sentence = card["yes" if expected else "no"][index]
            received = any(sentence in reply for reply in replies)
            actual = run["behavior"][card["inputs"].index(target)]
            outcome = ("정답" if actual == expected else "오답") if type(actual) is bool else actual
            counter[("회신 있음" if received else "회신 없음") + " · " + outcome] += 1
            details.append(dict(조건=arm, 과제=task, 시드=seed, 정책=policy, 입력=target,
                                기대값=expected, 실제값=actual, 직접회신=received))
        for value, actual in zip(card["inputs"], run["behavior"]):
            if value not in card["targets"]:
                counter["공개 규칙 정답"] += actual == (value in card["public_true"])
    return counts, details


if __name__ == "__main__":
    published = read(HERE / "정책판정_재집계.json")
    totals, rows = recount()
    assert published["집계"] == totals and published["근거"] == rows
    print(f"정책별 실제 회신과 최종 반환값 {len(rows)}행이 공개 결과와 일치합니다.")
