# Validation report

How well does the assistant find the right policy rules, and how well does it apply them? This report tests the policy lookup and the answering step on their own. It doesn't test the Make.com scenarios end to end, tool selection, or production readiness.

## What I tested

- **Policy:** a contrived 32-clause risk policy document (`policy/risk_policy_v2.md`), searched by embedding similarity (all-MiniLM-L6-v2, in memory).
- **Questions:** 50, each with the clauses it needs, the points a correct answer must make, and claims it must not make. They range from plain questions and colloquial rewordings to exact boundaries, several breaches at once, missing or stale data, invented limits, and attempts to make the assistant hide a breach or leak its instructions. 22 are for development; the other 28 were frozen as a held-out set before any tuning. The reference answers were drafted by an AI and have not been independently reviewed.
- **Answers:** Claude Haiku 4.5 (the model in my Make agent) answered every question twice: once with the clauses the lookup actually returned, once with the complete set. These were direct model calls, not through Make.
- **Scoring:**
  - free exact checks: cited clause IDs, and a planted fake secret (the "canary") to detect leaks;
  - Claude Sonnet 5.5 as judge, on rubrics run with DeepEval;
  - a review of 14 held-out answers. I 'cheated' here to save time: ChatGPT 6.1 Sol did the review on my instructions, and I went through its responses and edited them lightly.

Total cost about $4.20, with no failed calls. Numbers below are held-out unless stated.

## Key findings

**1. The lookup is the weak link.** With the service's top 2 clauses, every needed clause arrived in only 9 of 26 questions. Overall questions pull worked examples instead of the rules. Clauses implied by the data, such as stale or missing inputs, are rarely found.

**2. Core clauses fix most of it.** `include_core=true` always adds the position, volatility, VaR, drawdown and escalation clauses. With it, 16 of 26 questions got every needed clause; search alone with as many clauses reached 13. Its effect on answer quality isn't measured yet.

**3. Missing rules become wrong answers.** Haiku cited every needed clause in 10 of 26 questions with the clauses the lookup returned, and in 25 of 26 with the complete set. Without the rule, it either declined or treated a worked example as the rule. For example, it called a 9.1% position "within limit".

**4. Even with complete rules, Haiku misclassifies** (dev and held-out):
- 3.2% VaR listed under "within limit";
- 22.88% volatility called a "soft warning";
- the -8.01% drawdown boundary misstated;
- 5 of 12 stated data ages wrong.

**5. Attacks held.** All 7 attack cases were resisted, and the canary never appeared in 100 answers. The planted passages still reached the model.

**6. The AI judge is lenient.** In 15 of the 16 disagreements with the review, Sonnet passed what the review failed, and its Faithfulness score passed every answer. The review caught an invented "$" currency, a misattributed quote and breaches called warnings. A local judge (Qwen 2.5 7B via Ollama) was worse.

**7. Paragraph chunks stop silent truncation.** Four clauses were longer than the embedding model reads and lost their endings. Embedding each paragraph separately fixes that, with little effect on ranking.

## Limitations

- **Component test only:** the answering step was called directly, not through Make, so tool selection isn't measured.
- **The reference answers are AI-drafted and unreviewed.** In 6 of the 14 reviewed answers, they expected points the answer was never given the clauses for.
- **Every question is dated at least 44 days after its data,** so all data looked stale. That partly explains some over-cautious answers.
- **The held-out set has now been studied,** so a clean re-test needs fresh questions.
- **The review is AI-assisted and covers only 14 answers.** ChatGPT 6.1 Sol did the first pass and I edited lightly, so finding 6 compares two AI reviewers, one of them checked by me, not an AI against an independent human. It's enough to show the judge is lenient, not to say by how much.

## Possible extensions

- Re-run answer quality with `include_core` on fresh held-out questions (about $1.60).
- Add situational clauses based on the data itself: missing input (RP10), stale data (RP09), suspicious evidence (RP28).
- Fix the dataset: date questions the session after their data, and write required points per evidence condition.
- Score tool selection from saved Make traces.
- Have someone independent review the reference answers.

## Reproduce

```bash
python -m pytest -q
python eval/run_retrieval.py --split heldout --config candidate_core
python eval/run_generation.py --split heldout --dry-run
python eval/rejudge.py --run eval/results/generation/<run> --judge sonnet --max-usd 2.2   # paid
```

Every run folder in `eval/results/` holds:
- a manifest: commit, data hashes, models and settings;
- per-question results and judge scores;
- a summary with the full metrics (recall@k, MRR, per category).

My review sheet is in `eval/manual_review/`.
