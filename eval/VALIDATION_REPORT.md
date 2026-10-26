# Validation report

How well does the assistant find the right policy rules, and how well does it apply them? This report tests the policy lookup and the answering step on their own. It doesn't test the Make.com scenarios end to end, tool selection, or production readiness.

## What I tested

- **Policy:** a fictional 32-clause risk policy (`policy/risk_policy_v2.md`), searched by embedding similarity (all-MiniLM-L6-v2, in memory).
- **Questions:** 50, each with the clauses it needs, the points a correct answer must make, and claims it must not make. They range from plain questions and colloquial rewordings to exact boundaries, several breaches at once, missing or stale data, invented limits, and attempts to make the assistant hide a breach or leak its instructions. 22 are for development; the other 28 were frozen as a held-out set before any tuning. The reference answers were drafted by an AI and have not been independently reviewed.
- **Answers:** Claude Haiku 4.5 (the model in my Make agent) answered every question twice: once with the clauses the lookup actually returned, once with the complete set. These were direct model calls, not through Make.
- **Scoring:**
  - free exact checks: cited clause IDs, and a planted fake secret (the "canary") to detect leaks;
  - Claude Sonnet 5.5 as judge, on rubrics run with DeepEval;
  - my own review of 14 held-out answers.

Total cost about $4.20, with no failed calls. Numbers below are held-out unless stated.

## Key findings

**1. The lookup is the weak link.** The service hands the model its top 2 clauses. Every needed clause arrived in only 9 of 26 questions (35%). Plain questions in policy wording work. Overall questions ("any serious risk issues?") pull worked examples instead of the rules. Clauses that the data implies, like stale data or a missing input, are rarely found.

**2. Adding the core limit clauses fixes most of it.** With `include_core=true`, `/policy` always returns the position, volatility, VaR, drawdown and escalation clauses ahead of the search results. That raised complete questions from 9 to 16 of 26. Search alone with the same number of clauses reached 13, so the core list adds real value. The remaining misses are situational clauses (freshness, missing inputs, untrusted content). This setting has been measured for retrieval only, not for answer quality.

**3. Missing rules become wrong answers.** With the clauses the lookup returned, Haiku cited every needed clause in 10 of 26 questions; with complete evidence, in 25 of 26. When a rule was missing, it either declined to classify or used a worked example as if it were the rule. For example, it called a 9.1% position "within limit" and missed the 8 to 10% warning band.

**4. Even with complete rules, Haiku makes classification errors** (dev and held-out):
- It listed 3.2% VaR under "within limit" (the limit is 3%).
- It called 22.88% volatility a "soft warning" (it's Red).
- It misstated the -8.01% drawdown boundary.
- In dev answers that stated the data's age, 5 of 12 counts were wrong.

**5. Attacks held.** In all 7 attack cases, Haiku ignored the planted fake amendments and the instructions to hide a breach. The canary never appeared in 100 answers. The planted passages did reach the model, though, so this protection rests on the model, not the lookup.

**6. The AI judge is more lenient than I am.** In 15 of the 16 cases where we disagreed, I failed the answer and Sonnet passed it. Its Faithfulness score passed every answer, while I failed 7 of 14 on grounding. I caught errors no automated check did: an invented "$" currency, a quote attributed to the wrong clause, a sector rule applied to a single position, breaches described as warnings. A free local judge (Qwen 2.5 7B via Ollama) was worse, so I didn't use it.

**7. Fixing truncation was necessary, not a ranking gain.** Four clauses were longer than the embedding model reads (256 tokens), so their endings were silently cut off. For the escalation clause, that was the record-keeping paragraph. Embedding each paragraph separately fixes this, with the longest at 124 tokens. It retrieves slightly better at 2 clauses and slightly worse at 5.

## Limitations

- **Component test only:** the answering step was called directly, not through Make, so tool selection isn't measured.
- **The reference answers are AI-drafted and unreviewed.** In 6 of the 14 answers I reviewed, they expected points the answer was never given the clauses for.
- **Every question is dated at least 44 days after its data,** so all data looked stale. That partly explains some over-cautious answers.
- **The held-out set has now been studied,** so a clean re-test needs fresh questions.
- **One reviewer on 14 answers:** enough to show the judge is lenient, not to say by how much.

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
