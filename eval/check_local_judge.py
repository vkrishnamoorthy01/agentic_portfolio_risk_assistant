"""Sanity check of a judge before using it: can it tell a correct answer from a wrong one?

    python eval/check_local_judge.py            # local Ollama judge, free
    python eval/check_local_judge.py --judge sonnet

Scores two hand-written answers to dev case D13 (VaR unavailable), with the
reference evidence: one correct (declines to classify, cites RP10/RP25/RP17),
one wrong (invents a VaR value and a 5% limit). Every metric, Faithfulness
included, should score the correct answer clearly higher. Both answers were
written for this check; neither is a model output.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "analytics"))

import retrieval  # noqa: E402
import run_generation as rg  # noqa: E402

ANSWERS = {
    "correct": ("I can't say whether the portfolio passes the VaR limit. The analytics output has no VaR value: "
                "historical_var_99_1d is null because the ITC return for 2026-09-10 is missing. Under RP10 a measure "
                "with missing inputs can't be classified as within limit, and under RP25 the missing measure should be "
                "escalated to the risk officer. The limit itself is 99% one-day historical VaR of at most 3% of NAV (RP17)."),
    "wrong": ("Yes, the portfolio passes. VaR is about 1.5% of NAV, comfortably inside the 5% limit in RP17, "
              "so nothing needs escalating."),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--judge", choices=sorted(rg.JUDGE_MODELS), default="ollama")
    args = parser.parse_args()

    data, fixtures, injected = rg.load_split("dev")
    case = next(c for c in data["cases"] if c["case_id"] == "D13")
    clauses = {c.clause_id: c for c in retrieval.parse_clauses(rg.POLICY_VERSION)}
    evidence = rg.evidence_for(case, "reference", clauses, injected)
    prompt = {"user_message": rg.user_message(case, evidence, fixtures), "adversarial": False}

    judge = rg.make_judge(args.judge)
    results = {}
    for label, answer in ANSWERS.items():
        start = time.time()
        results[label] = {"answer": answer, "scores": rg.judge_one(judge, case, prompt, answer, faithfulness=True),
                          "seconds": round(time.time() - start, 1)}
        print(label, {m: s["score"] for m, s in results[label]["scores"].items()}, f"{results[label]['seconds']}s")

    verdict = {m: ("separates" if (results["correct"]["scores"][m]["score"] or 0) > (results["wrong"]["scores"][m]["score"] or 0)
                   else "does not separate")
               for m in results["correct"]["scores"]}
    print("verdict", verdict)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "eval" / "results" / "judge_check" / f"{args.judge}_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    record = {"command": " ".join(["python", "eval/check_local_judge.py", *sys.argv[1:]]),
              "git_commit": rg.git("rev-parse", "HEAD"), "judge_backend": args.judge,
              "judge_model": rg.JUDGE_MODELS[args.judge], "case_id": "D13", "condition": "reference",
              "verdict": verdict, "results": results}
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("saved to", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
