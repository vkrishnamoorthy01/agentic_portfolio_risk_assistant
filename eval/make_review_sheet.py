"""Blinded manual-review sheet for generated answers, and the later judge-vs-human comparison.

    python eval/make_review_sheet.py --run eval/results/generation/heldout_full_<stamp>
    python eval/make_review_sheet.py --run eval/results/generation/heldout_full_<stamp> --compare

The sheet holds the question, the evidence IDs the model saw, the answer and
the reference elements, in a shuffled order. It never contains judge scores
or model names; those stay in judge_scores.jsonl and the run manifest. The
reviewer fills the score columns by hand. --compare reads the filled sheet and
reports agreement with the judge per dimension; until a human has filled it,
that comparison is pending.

Human scale per dimension: Y (meets the criterion), N (does not), NA (not
applicable). The judge counts as Y when its score is at least 0.5 (DeepEval's
default threshold).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "eval" / "dataset"
SHEETS = ROOT / "eval" / "manual_review"

# 14 held-out cases, stratified toward retrieval failures and adversarial inputs.
REVIEW_CASES = ["H05", "H09", "H10", "H11", "H12", "H14", "H15", "H17", "H20", "H21", "H22", "H23", "H24", "H25"]
REVIEW_CONDITION = "retrieved"  # what a user of the service would actually get
SEED = 20261025

# Human column -> judge metric
DIMENSIONS = {
    "grounded": "faithfulness",
    "policy_applied_correctly": "policy_application",
    "complete": "completeness",
    "no_forbidden_claim": "forbidden_claims",
    "abstained_appropriately": "abstention",
    "resisted_injection": "injection_resistance",
}
EXTRA_COLUMNS = ["citations_correct", "notes", "reviewer", "review_date"]


def load_cases(split: str) -> dict:
    return {c["case_id"]: c for c in json.loads((DATASET / f"cases_{split}.json").read_text(encoding="utf-8"))["cases"]}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_sheet(run: Path) -> Path:
    cases = load_cases("heldout")
    outputs = {(o["case_id"], o["condition"]): o for o in read_jsonl(run / "outputs.jsonl")}
    rows = []
    for case_id in REVIEW_CASES:
        out = outputs.get((case_id, REVIEW_CONDITION))
        case = cases[case_id]
        rows.append({
            "case_id": case_id, "category": case["category"], "question": case["question"],
            "fixture": case["fixture"] or "", "evidence_shown": " ".join(out["evidence_ids"]) if out else "",
            "answer": out.get("answer", "") if out else "",
            "generation_error": "" if out and out["ok"] else (out or {}).get("error", "not generated"),
            "required_elements": "; ".join(case["required_elements"]),
            "forbidden_claims": "; ".join(case["forbidden_claims"]),
            "criteria": case["criteria"],
            **{d: "" for d in DIMENSIONS}, **{c: "" for c in EXTRA_COLUMNS},
        })
    random.Random(SEED).shuffle(rows)
    for i, row in enumerate(rows, start=1):
        row["review_id"] = f"R{i:02d}"
    SHEETS.mkdir(exist_ok=True)
    path = SHEETS / f"review_sheet_{run.name}.csv"
    fields = ["review_id", "case_id", "category", "question", "fixture", "evidence_shown", "answer",
              "generation_error", "required_elements", "forbidden_claims", "criteria", *DIMENSIONS, *EXTRA_COLUMNS]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def compare(run: Path) -> None:
    path = SHEETS / f"review_sheet_{run.name}.csv"
    with path.open(encoding="utf-8", newline="") as f:
        human = {r["case_id"]: r for r in csv.DictReader(f)}
    judged = {j["case_id"]: j["scores"] for j in read_jsonl(run / "judge_scores.jsonl") if j["condition"] == REVIEW_CONDITION}
    filled = [r for r in human.values() if any(r[d].strip() for d in DIMENSIONS)]
    if not filled:
        print("Comparison pending: no human scores in", path.relative_to(ROOT))
        return
    print(f"{len(filled)} of {len(human)} rows have human scores")
    for dim, metric in DIMENSIONS.items():
        agree = total = 0
        for r in filled:
            h = r[dim].strip().upper()
            score = judged.get(r["case_id"], {}).get(metric, {}).get("score")
            if h not in ("Y", "N") or score is None:
                continue
            total += 1
            agree += (h == "Y") == (score >= 0.5)
        print(f"  {dim:26s} agreement {agree}/{total}" + (f" ({agree / total:.0%})" if total else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="a held-out generation run directory")
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    run = args.run if args.run.is_absolute() else ROOT / args.run
    if args.compare:
        compare(run)
    else:
        print("wrote", make_sheet(run).relative_to(ROOT))


if __name__ == "__main__":
    main()
