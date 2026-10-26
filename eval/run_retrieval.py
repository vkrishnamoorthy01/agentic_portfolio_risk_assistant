"""Retrieval-only evaluation (no generation, no network): how well /policy finds the required clauses.

    python eval/run_retrieval.py --split dev --config candidate
    python eval/run_retrieval.py --split heldout --config candidate     # once per frozen config

Configurations (policy v2.1, all-MiniLM-L6-v2, in-memory cosine similarity):
  baseline   whole clauses as passages, as the pre-v2 code chunked them. Four
             clauses exceed the 256-token limit; for this measurement they are
             embedded truncated, exactly as the old code would have done.
  candidate  paragraph passages with a clause/title/version header (the
             service default since this integration).

Relevance and denominators
  required_clauses are relevant (binary). supporting_clauses are not counted.
  Ranking is over distinct clauses (each clause scored by its best passage).
  recall@k   = |required in top k clauses| / |required|, averaged over cases
               that have at least one required clause.
  complete@k = share of those cases with every required clause in the top k.
  MRR        = mean reciprocal rank of the first required clause.
  Cases with no required clauses (out-of-scope, value-only) are excluded and
  listed separately with their top-ranked clause. For cases with an
  injected_passage, the injected text is added to an isolated copy of the
  index and its rank is reported; it is never relevant.
Scores are cosine similarities used for ranking only, not probabilities of
correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import retrieval  # noqa: E402

DATASET = ROOT / "eval" / "dataset"
KS = (1, 2, 3, 5, 8)
CONFIGS = {"baseline": "clause", "candidate": "paragraph"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def evaluate_case(case: dict, chunking: str, injected: dict) -> dict:
    extra = None
    if case.get("injected_passage"):
        inj = injected[case["injected_passage"]]
        extra = [retrieval.Passage(f"{inj['clause_id']}.p1", inj["clause_id"], inj["title"], "injected",
                                   inj["text"], f"{inj['title']}. {inj['text']}")]
    ranked = retrieval.rank_clauses(case["question"], "v2.1", chunking, extra_passages=extra, allow_truncation=True)
    order = [r["clause_id"] for r in ranked]
    required = case["required_clauses"]
    ranks = {c: order.index(c) + 1 for c in required}
    row = {
        "case_id": case["case_id"], "category": case["category"], "question": case["question"],
        "required_clauses": required, "required_ranks": ranks,
        "top8": [{"clause_id": r["clause_id"], "score": r["score"], "passage_id": r["passage_id"]} for r in ranked[:8]],
    }
    if extra:
        row["injected_rank"] = order.index(extra[0].clause_id) + 1
    if required:
        row["recall"] = {k: sum(r <= k for r in ranks.values()) / len(required) for k in KS}
        row["complete"] = {k: all(r <= k for r in ranks.values()) for k in KS}
        row["rr"] = 1.0 / min(ranks.values())
    return row


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if r["required_clauses"]]
    n = len(scored)

    def agg(group: list[dict]) -> dict:
        m = len(group)
        return {
            "n": m,
            "recall_at_k": {k: round(sum(r["recall"][k] for r in group) / m, 3) for k in KS},
            "complete_at_k": {k: f"{sum(r['complete'][k] for r in group)}/{m}" for k in KS},
            "mrr": round(sum(r["rr"] for r in group) / m, 3),
        }

    by_category = defaultdict(list)
    for r in scored:
        by_category[r["category"]].append(r)
    multi = [r for r in scored if len(r["required_clauses"]) > 1]
    return {
        "cases_total": len(rows), "cases_scored": n,
        "excluded_no_required_clauses": [{"case_id": r["case_id"], "top_clause": r["top8"][0]["clause_id"]}
                                         for r in rows if not r["required_clauses"]],
        "overall": agg(scored),
        "single_clause": agg([r for r in scored if len(r["required_clauses"]) == 1]),
        "multi_clause": agg(multi) if multi else None,
        "by_category": {c: agg(g) for c, g in sorted(by_category.items())},
        "injected_passage_ranks": {r["case_id"]: r["injected_rank"] for r in rows if "injected_rank" in r},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", choices=["dev", "heldout"], required=True)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    args = parser.parse_args()

    data_file = DATASET / f"cases_{args.split}.json"
    cases = json.loads(data_file.read_text(encoding="utf-8"))["cases"]
    injected = json.loads((DATASET / "fixtures.json").read_text(encoding="utf-8"))["injected_passages"]
    chunking = CONFIGS[args.config]
    rows = [evaluate_case(c, chunking, injected) for c in cases]
    summary = summarize(rows)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "eval" / "results" / "retrieval" / f"{args.split}_{args.config}_{stamp}"
    out.mkdir(parents=True)
    model = retrieval._get_model()
    manifest = {
        "run": f"retrieval {args.split} {args.config}", "started_utc": stamp,
        "command": f"python eval/run_retrieval.py --split {args.split} --config {args.config}",
        "git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(git("status", "--porcelain", "--", "analytics", "eval", "policy")),
        "policy_version": "v2.1", "policy_sha256_normalized": retrieval.corpus_sha256("v2.1"),
        "dataset_file": data_file.name, "dataset_sha256": sha256_file(data_file),
        "fixtures_sha256": sha256_file(DATASET / "fixtures.json"),
        "embedding_model": retrieval.EMBEDDING_MODEL_NAME, "max_seq_length": model.max_seq_length,
        "config": args.config, "chunking": chunking, "ranking": "distinct clauses, each by its best passage",
        "passages": len(retrieval.build_passages("v2.1", chunking)), "ks": list(KS),
        "python": platform.python_version(),
        "packages": {p: metadata.version(p) for p in ("sentence-transformers", "torch", "transformers", "numpy")},
        "errors": [], "exclusions": summary["excluded_no_required_clauses"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    with (out / "results.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")

    o = summary["overall"]
    print(f"{args.split}/{args.config}: {summary['cases_scored']} scored of {summary['cases_total']}")
    print("  recall@k  ", o["recall_at_k"])
    print("  complete@k", o["complete_at_k"])
    print("  MRR", o["mrr"], "| multi-clause complete@5", (summary["multi_clause"] or {}).get("complete_at_k", {}).get(5))
    print("  injected ranks", summary["injected_passage_ranks"])
    print("  saved to", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
