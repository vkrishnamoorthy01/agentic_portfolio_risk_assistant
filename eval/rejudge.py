"""Score the saved answers of a generation run again with another judge, without regenerating.

    python eval/rejudge.py --run eval/results/generation/dev_full_<stamp> --judge sonnet --max-usd 2.5
    python eval/rejudge.py --run <same run> --judge sonnet --cases D17,D08    # small check first

Reads the run's prompts.jsonl and outputs.jsonl and writes
judge_scores_<judge>_<stamp>.jsonl and rejudge_<judge>_<stamp>.json into the
same folder; the original judge_scores.jsonl is left as it was. The same GEval
rubrics are used. Faithfulness is off unless --faithfulness is given (it adds
about three calls per answer); --only-faithfulness runs it without the rubrics. --max-usd stops a paid judge at a spending cap
(list prices); answers not reached are listed in the manifest as not judged.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import run_generation as rg  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, required=True, help="a generation run folder with outputs.jsonl")
    parser.add_argument("--judge", choices=sorted(rg.JUDGE_MODELS), required=True)
    parser.add_argument("--max-usd", type=float, help="spending cap for a paid judge")
    parser.add_argument("--faithfulness", action="store_true")
    parser.add_argument("--only-faithfulness", action="store_true", help="skip the GEval rubrics")
    parser.add_argument("--condition", choices=["retrieved", "reference"], help="judge only one evidence condition")
    parser.add_argument("--cases", help="comma-separated case IDs")
    args = parser.parse_args()

    run = args.run if args.run.is_absolute() else ROOT / args.run
    run_manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    split = "heldout" if run.name.startswith("heldout") else "dev"
    cases = {c["case_id"]: c for c in json.loads((rg.DATASET / f"cases_{split}.json").read_text(encoding="utf-8"))["cases"]}
    prompts = {(p["case_id"], p["condition"]): p for p in read_jsonl(run / "prompts.jsonl")}
    outputs = [o for o in read_jsonl(run / "outputs.jsonl") if o.get("ok")]
    if args.condition:
        outputs = [o for o in outputs if o["condition"] == args.condition]
    if args.cases:
        wanted = set(args.cases.split(","))
        outputs = [o for o in outputs if o["case_id"] in wanted]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    scores_path = run / f"judge_scores_{args.judge}_{stamp}.jsonl"
    judge = rg.make_judge(args.judge, max_usd=args.max_usd)
    manifest = {
        "run": f"rejudge {run.name} with {args.judge}", "started_utc": stamp,
        "command": " ".join(["python", "eval/rejudge.py", *sys.argv[1:]]),
        "git_commit": rg.git("rev-parse", "HEAD"), "source_run": run.name,
        "source_run_commit": run_manifest.get("git_commit"),
        "judge_backend": args.judge, "judge_model": rg.JUDGE_MODELS[args.judge],
        "judge_settings": rg.CLAUDE_JUDGE_SETTINGS.get(args.judge), "max_usd": args.max_usd,
        "faithfulness_metric": "run" if args.faithfulness or args.only_faithfulness else "omitted (not requested)",
        "rubrics": "omitted (--only-faithfulness)" if args.only_faithfulness else "run",
        "condition": args.condition or "both",
        "geval_rubrics": rg.GEVAL_RUBRICS, "answers": len(outputs), "errors": [], "not_judged": [],
        "scores_file": scores_path.name,
    }
    stopped = None
    with scores_path.open("w", encoding="utf-8", newline="\n") as f:
        for i, o in enumerate(outputs, start=1):
            key = (o["case_id"], o["condition"])
            if stopped:
                manifest["not_judged"].append(list(key))
                continue
            try:
                scores = rg.judge_one(judge, cases[o["case_id"]], prompts[key], o["answer"],
                                      faithfulness=args.faithfulness or args.only_faithfulness,
                                      rubrics=not args.only_faithfulness)
            except rg.BudgetExceeded as exc:
                stopped = str(exc)
                manifest["not_judged"].append(list(key))
                continue
            for metric, s in scores.items():
                if s.get("error"):
                    manifest["errors"].append({"case_id": key[0], "condition": key[1], "judge_metric": metric, "error": s["error"]})
            f.write(json.dumps({"case_id": key[0], "condition": key[1], "scores": scores}) + "\n")
            usd = getattr(judge, "usage", {}).get("usd", 0.0)
            print(f"  [{i}/{len(outputs)}] {key[0]} {key[1]} " + " ".join(
                f"{m[:4]}={s['score'] if s['score'] is not None else 'ERR'}" for m, s in scores.items()) + f"  ${usd:.3f}")

    manifest["finished_utc"] = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest["stopped"] = stopped
    manifest["judge_usage"] = getattr(judge, "usage", None)
    (run / f"rejudge_{args.judge}_{stamp}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"done: {len(outputs) - len(manifest['not_judged'])} judged, {len(manifest['not_judged'])} not judged, "
          f"{len(manifest['errors'])} metric errors, usage {manifest['judge_usage']}" + (f"; stopped: {stopped}" if stopped else ""))


if __name__ == "__main__":
    main()
