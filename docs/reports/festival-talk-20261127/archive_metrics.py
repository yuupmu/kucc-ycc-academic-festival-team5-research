"""Reproduce the talk's model comparisons and per-path costs from saved local requests."""
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ARCHIVE = HERE.parents[2]
FAMILY = ARCHIVE / "var/family-100-v1"
AGENDAS = ARCHIVE / "experiments/decision-ledger-20261126"
RECEIPTS = ARCHIVE / "experiments/ledger-receipts-20261126"


def read(path):
    return json.loads(path.read_text())


def tokens(calls, folder):
    total = 0
    for call in calls:
        usage = read(folder / (call + ".json"))["usage"]
        assert usage["prompt_tokens"] + usage["completion_tokens"] == usage["total_tokens"]
        total += usage["total_tokens"]
    return total


def transfer():
    comparison = read(FAMILY / "comparison.json")
    fields = ("correct", "grounded_correct", "topics", "questions", "tokens")
    performance = {arm: {k: row[k] for k in fields} for arm, row in comparison["summary"].items()}
    pairs = {}
    for label, row in comparison["paired"].items():
        gain, loss = set(row["improved"]), set(row["regressed"])
        assert gain.isdisjoint(loss)
        left, right = label.split(" -> ")
        assert performance[right]["correct"] - performance[left]["correct"] == len(gain) - len(loss)
        pairs[label] = {"gain": len(gain), "same_correctness": 100 - len(gain | loss), "loss": len(loss)}
    return {"scores": performance, "per_input_pairs": pairs}


def upload_costs():
    snapshot = read(FAMILY / "runs/mixed/upload/abc-1-snapshot.json")
    roles = {}
    for call in snapshot["calls"]:
        role = read(FAMILY / "calls" / (call + ".json"))["role"]
        if role in ("main", "observer-A", "observer-B", "observer-C"):
            assert role not in roles
            roles[role] = call
    draft = tokens([roles["main"]], FAMILY / "calls")
    reviews = tokens([roles[k] for k in ("observer-A", "observer-B", "observer-C")], FAMILY / "calls")
    agenda = read(AGENDAS / "agendas/upload/agenda.json")["agenda"]
    preparation = tokens(agenda["calls"], AGENDAS / "calls")
    result = {"draft": draft, "three_reviews": reviews, "prepare_questions_and_public_rules": preparation}
    paths = {}
    for arm, stage in (("include", "initial"), ("exclude", "initial"), ("unmentioned", "initial"),
                       ("unmentioned", "yes"), ("unmentioned", "no")):
        state = read(RECEIPTS / "runs/upload" / arm / stage / "state.json")
        rounds = [tokens(turn["calls"], RECEIPTS / "calls") for turn in state["history"]]
        paths[f"{arm}/{stage}"] = {"receipt_rounds": rounds, "logical_path": draft + reviews + preparation + sum(rounds)}
    result["paths"] = paths
    return result


if __name__ == "__main__":
    print(json.dumps({"transfer_100": transfer(), "canonical_upload_tokens": upload_costs()},
                     ensure_ascii=False, indent=2))
