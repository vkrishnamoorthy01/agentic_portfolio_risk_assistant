# Validation report: policy v2.1 integration and evaluation

Merged into `main` (49fa4d2), with the manual review added afterwards. Dates 2026-10-25 to 2026-10-26. Scope: the policy retrieval component of the Portfolio Risk Assistant, and the answering step measured by direct model calls. Nothing here measures the Make.com v3/v4 scenarios end to end, tool selection, or production readiness.

## 1. Implemented

- **Versioned policy corpus.** `policy/risk_policy_v1.md` (the original 5 sections, kept as the baseline) and `policy/risk_policy_v2.md` (v2.1, 32 clauses RP01-RP32). `POLICY_VERSION` selects one; v2.1 is the default. The implementation appendix is not in the corpus.
- **Clause-aware passages.** v2.1 is embedded as 98 paragraph passages, each prefixed with clause ID, title and policy version. Clauses are ranked by their best passage and returned whole, so a limit is never split from its exceptions.
- **Truncation guard.** Building the index raises `PassageTooLongError` if any passage exceeds the model's 256-token limit. Committed manifests (`policy/index_v1.json`, `policy/index_v2.1.json`) record every passage's token count and a line-ending-normalized corpus hash.
- **Same retrieval stack.** all-MiniLM-L6-v2, in-memory cosine similarity. No vector database. Risk limits and calculation methods are unchanged; a test compares the v1 and v2.1 thresholds.
- **Price data changed after the dataset was frozen.** The service now reads the latest downloaded Kite or IBKR prices by default (IBKR live, as of 2026-10-23, on this machine). The evaluation does not call the service. Its fixtures are fixed: F0 is the synthetic snapshot as of 2026-09-11, and F1-F10 are hypothetical variants. The results below are therefore unaffected.
- **Golden dataset** `golden-v1`: 50 cases, 22 dev and 28 held-out. The held-out split was frozen in `eval/dataset/FREEZE.json` before any tuning. Every reference answer was drafted by an AI and is marked `ai_drafted_unreviewed`; none has been independently reviewed. Dev cases built from the manual's worked examples are flagged, and held-out has none.
- **Retrieval evaluation** `eval/run_retrieval.py`.
- **Generation evaluation** `eval/run_generation.py`:
  - Generator: Claude Haiku 4.5, the Make v4 model.
  - Two evidence conditions per case, a synthetic canary, and deterministic checks.
  - The analytics fixture is supplied as tool output.
  - A dry-run mode makes no network calls.
- **Judging** with DeepEval GEval rubrics: policy application, completeness, forbidden claims, abstention, and injection resistance on adversarial cases. `eval/rejudge.py` scores saved answers with another judge without regenerating them, under a spending cap. `eval/check_local_judge.py` is a sanity check that scores one correct and one wrong hand-written answer.
- **Blinded review sheet** `eval/make_review_sheet.py` and `eval/manual_review/README.md`.
- **Tests**: 51 offline tests. CI needs no API key and makes no paid calls.

Why DeepEval rather than Ragas: the questions that matter here are policy-specific (correct band and inclusivity, abstention on missing inputs, resisting injected limits). GEval takes custom rubrics for these directly. Ragas centers on generic RAG metrics and would need custom metrics for most of this.

## 2. Actually executed

| Run | Model calls | Cost | Saved under |
|---|---|---|---|
| Retrieval, dev, baseline and candidate | local only | 0 | `eval/results/retrieval/dev_*` |
| Retrieval, held-out, baseline and candidate, once each | local only | 0 | `eval/results/retrieval/heldout_*` |
| Local judge sanity check | local only | 0 | `eval/results/judge_check/` |
| Generation smoke run, D13 (2 answers, local judge) | Haiku 4.5 | $0.006 | `eval/results/generation/dev_full-smoke_*` |
| Generation, dev (44 answers), local Qwen judge | Haiku 4.5 | $0.099 | `eval/results/generation/dev_full_20261026T072541Z` |
| Sonnet 5.5 checks on 4 dev answers (before and after the rubric fix) | Sonnet 5.5 | $0.27 | same folder, `judge_scores_sonnet_*0759*`, `*0801*` |
| Sonnet 5.5 re-judge, dev (44 answers) | Sonnet 5.5 | $1.18 | same folder, `judge_scores_sonnet_20261026T080257Z.jsonl` |
| Generation, held-out (56 answers), once | Haiku 4.5 | $0.146 | `eval/results/generation/heldout_generate_20261026T081830Z` |
| Sonnet 5.5 re-judge, held-out (56 answers), once | Sonnet 5.5 | $1.65 | same folder, `judge_scores_sonnet_20261026T082235Z.jsonl` |
| Sonnet 5.5 Faithfulness, held-out (2-answer cost check, then 28 retrieved-evidence answers) | Sonnet 5.5 | $0.83 | same folder, `judge_scores_sonnet_20261026T094300Z.jsonl`, `judge_scores_sonnet_20261026T094345Z.jsonl` |
| Test suite | local only | 0 | 51 passed |

All costs are at list prices. Total paid: about $4.20. Every generation and judge call completed: 0 failed calls, 0 judge metric errors, 0 answers not judged. The manual review was done by Vivek Krishnamoorthy on 2026-10-26: 14 held-out answers built from retrieved evidence (section 3).

## 3. Verified by saved evidence

### Truncation
Whole v2.1 clauses: 4 of 32 (13%) exceed 256 tokens (RP03 258, RP25 276, RP29 264, RP32 396). Embedded whole, their ends would be dropped silently; for RP25 Escalation, that is the record-keeping paragraph. Paragraph passages: 0 of 98 exceed the limit. The longest is 124 tokens.

### Retrieval (clause level)
Definitions:
- A case's required clauses are the relevant set. `complete@k` means all required clauses are in the top k.
- Cases with no required clauses are excluded (dev 1 of 22; held-out 2 of 28) and listed in each summary.
- Scores are cosine similarities used for ranking. They are not probabilities.
- Baseline = whole clauses (pre-v2 chunking, 4 truncated). Candidate = paragraph passages, now the service default.
- The service returns **k = 2**.

| Split | Config | complete@2 | complete@5 | Multi-clause complete@2 | Multi-clause complete@5 | MRR |
|---|---|---|---|---|---|---|
| dev (21) | baseline | 9/21 (43%) | 14/21 (67%) | 0/8 (0%) | 2/8 (25%) | 0.648 |
| dev (21) | candidate | 9/21 (43%) | 14/21 (67%) | 0/8 (0%) | 2/8 (25%) | 0.686 |
| held-out (26) | baseline | 5/26 (19%) | 13/26 (50%) | 0/17 (0%) | 6/17 (35%) | 0.746 |
| held-out (26) | candidate | 9/26 (35%) | 11/26 (42%) | 3/17 (18%) | 5/17 (29%) | 0.743 |

At the service's k = 2, the candidate completes more held-out cases than the baseline: 9 against 5. At k = 5 it completes fewer: 11 against 13. The candidate was adopted because it removes truncation, not because it retrieves better. On held-out it is not consistently better.

Failure patterns, from the per-case files:
- **Single-clause questions in policy vocabulary mostly succeed.** Held-out direct 2/2 and paraphrase 3/3 at k = 5.
- **Multi-clause answers rarely arrive complete.** At k = 2, 3 of 17 held-out multi-clause cases (18%) are complete.
- **Evidence implied by the tool output is not retrievable from the question.** Examples:
  - RP10 missing inputs at rank 26 (H17).
  - RP09 freshness at rank 15 (H15).
  - RP28 untrusted content at rank 29-32 (H21, H22, H24).
  - RP13 position at rank 27 when the question is "does anything need escalating?" (H13).
- **Overall and escalation questions miss the core limit clauses.** H12 (all four breached): RP13 rank 32, RP19 rank 25. H14 overall: RP19 rank 26.
- **Injected passages are retrieved.** In 2 of 2 injected cases, the injected passage reached the top 2 handed to the model. D18 was rank 1. H22 was rank 1 (baseline) and rank 2 (candidate).

### Answer quality (component level)
Haiku 4.5 answers each case twice: with the clauses the service retrieves (top 2), and with the complete reference clauses. The gap between the two is the cost of retrieval misses.

**Deterministic checks (free, exact):**

| | dev retrieved | dev reference | held-out retrieved | held-out reference |
|---|---|---|---|---|
| All required clauses cited | 10/21 (48%) | 21/21 (100%) | 10/26 (38%) | 25/26 (96%) |
| Canary leaked | 0/22 | 0/22 | 0/28 | 0/28 |
| Clause IDs outside RP01-RP32 | 0/22 | 0/22 | 0/28 | 0/28 |

**Sonnet 5.5 judge.** Pass means a GEval score of 0.5 or higher. The judge scores are an AI assessment, not human-validated.

| Rubric | dev retrieved | dev reference | held-out retrieved | held-out reference |
|---|---|---|---|---|
| policy_application | 19/22 (86%) | 20/22 (91%) | 27/28 (96%) | 27/28 (96%) |
| completeness | 19/22 (86%) | 22/22 (100%) | 25/28 (89%) | 27/28 (96%) |
| forbidden_claims | 22/22 (100%) | 22/22 (100%) | 28/28 (100%) | 25/28 (89%) |
| abstention | 20/22 (91%) | 22/22 (100%) | 26/28 (93%) | 24/28 (86%) |
| injection_resistance | 3/3 | 3/3 | 4/4 | 4/4 |

Findings:
- **Retrieval misses become answer failures.** With the top 2 clauses, Haiku cites every required clause in 10 of 26 held-out cases (38%), against 25 of 26 (96%) with reference evidence. Three examples, each failing with retrieved evidence and passing with reference evidence:
  - **D10** (checked by hand): Haiku declines to classify anything.
  - **H11** (checked by hand): with RP13 missing, it treats RP30's worked examples as rules and calls a 9.1% position "within limit", missing the 8-10% warning band.
  - **D05** (judge-flagged): the volatility clause is missing, so Haiku says there is no threshold.
- **Haiku makes classification errors even with complete evidence** (checked by hand):
  - **H12:** VaR 3.2% sits under a "within limit" heading although the text says it is over 3%, so four escalation triggers are reported as three.
  - **D17:** 22.88% volatility is called a "soft warning" when it is a breach.
  - **D04:** says values "below -8.01%" breach, when -8.01% itself breaches.
- **Over-abstention on stale data** (judge-flagged, not hand-checked). In H04 and H28 the evidence was enough to answer. Haiku leaned on the 44-day-old snapshot and declined more than the policy requires. This is the main reason held-out reference scores lower than held-out retrieved on abstention.
- **Date arithmetic.** In dev answers that stated the data's age, 5 of 12 counts were wrong: two said 14 days and three said 45, against a true gap of 44.
- **Adversarial inputs held.** All 7 adversarial cases passed the injection-resistance rubric in both conditions: injected limits, user instructions to hide breaches, another fund's figures, and requests for configuration. The canary never appeared in any of the 100 answers.

### Manual review (human)
Vivek Krishnamoorthy scored the 14 held-out answers built from retrieved evidence, blind to the judge scores. Sheet: `eval/manual_review/review_sheet_heldout_generate_20261026T081830Z.csv`.

| Dimension | Human pass | Agreement with Sonnet judge |
|---|---|---|
| grounded (judge: Faithfulness) | 7/14 (50%) | 7/14 (50%) |
| policy_applied_correctly | 9/13 (69%) | 10/13 (77%) |
| complete | 8/14 (57%) | 10/14 (71%) |
| no_forbidden_claim | 14/14 (100%) | 14/14 (100%) |
| abstained_appropriately | 13/14 (93%) | 12/14 (86%) |
| resisted_injection | 4/4 | 4/4 |
| citations_correct (no judge metric) | 9/13 (69%) | n/a |

- **The judge is more lenient than the human.** In 15 of the 16 disagreements, the human failed the answer and Sonnet passed it. The gap is widest on grounding: the human failed 7 of 14 answers, while Faithfulness gave every one 0.93 or more.
- **The human review found errors no automated check caught:**
  - **H09:** a "$" currency symbol for an amount that has no currency in the data.
  - **H24:** a quotation attributed to RP20 that is actually in RP19.
  - **H15:** RP14's sector/issuer rule applied to a single position, which RP13 governs.
  - **H22:** a Red volatility reading and a drawdown breach described as a "soft warning or escalation band".
- **Two findings in H22 are partly a sheet error.** The human marked citing "AMD-15" as invented, but AMD-15 is the label the model was shown for the injected passage. The sheet listed the internal ID (INJECTED-2) instead. The generator now writes the shown label. The human scores are reported as given.
- **Criteria issues raised by the reviewer.** In 6 of 14 rows (H11, H14, H15, H17, H20, H21), required elements depend on clauses that were not in the retrieved evidence, so an answer could not meet them from what it was shown. The reference elements were written for complete evidence. A clarification was also noted on H09 (rounding precision), H23 (sector data absent from the output, not uncomputable) and H25 (the reviewer could not see the system prompt or canary).
- **This is one reviewer on 14 answers.** That is enough to show the judge is lenient, not to put a precise number on how lenient.

### Judges
- **Rubric bug, fixed before held-out.** Two rubric steps said "score 1", but GEval scores on 0-10, so answers meeting the criterion got 0.1. The dev Qwen scores and the first 4-answer Sonnet check used the old wording. Every score in the table above uses the corrected wording.
- **Local Qwen 2.5 7B judge, used on dev only.** On the sanity check, its Faithfulness scores ranked a wrong answer above a correct one, so Faithfulness was not run. On dev answers it also made clear errors, such as scoring the strong D17 answer 0.0 on policy application with a quote that is not in the answer. It agreed with Sonnet's pass/fail call in 39 of 44 answers on policy application and completeness, and 41 of 44 on abstention. Sonnet was chosen on dev, before held-out was run.
- **Faithfulness, with Sonnet 5.5, on the 28 held-out answers built from retrieved evidence only.** The budget did not cover the reference condition or dev. All 28 pass, and 27 of 28 score a perfect 1.0. That includes H11, which applies the wrong rule (it calls a 9.1% position "within limit") while every statement in it is supported by the evidence it was shown. Faithfulness measures whether claims are supported by the context, not whether the policy was applied correctly. Haiku's errors here are of the second kind, so the policy_application rubric and the hand checks are what catch them.
- **Sonnet's reasons were spot-checked, not systematically reviewed.** Its scores for D04, D08, D10, D17 (both conditions), H11 and H12 were checked by hand against the answers, and all seven matched. That is not a measured agreement rate; the manual review provides one.

## 4. Pending

| Item | Blocked on |
|---|---|
| golden-v2 dataset fixes (below) | budget for a re-run: about $3.10 for all 50 cases, or about $1.60 for the 26 that use portfolio numbers |
| Faithfulness for the reference condition and dev | about $0.035 per answer (about $2.50 for the remaining 72 answers) |
| Tool-selection evaluation | saved Make.com tool traces (none in the repo) |
| Independent review of reference answers | a reviewer other than the drafting AI |
| Retrieval change | your decision; would be tuned on dev and then scored once on a fresh held-out set, since this one has now been used |

The retrieval change that the evidence supports, though it was not tested: for portfolio and overall questions, always include the core limit clauses (RP13, RP15, RP17, RP19, RP25 and RP08-RP10), and use semantic search only for the remainder. Raising top_k alone helps less: complete@5 is still 42-50% on held-out.

**Known limitation: question dating.** Every case is dated 2026-10-25, but every fixture is dated 2026-09-11 (F8 is 2026-08-14). So every portfolio snapshot looked at least 44 days stale, not only the freshness cases. The over-abstention seen in H04 and H28 is therefore partly an artifact of the dataset, not purely a model weakness. The main findings do not depend on dates: retrieval misses, classification errors, injection resistance and canary handling.

golden-v2 fixes, for the next re-run:
- Date each question the session after its data, so that only the freshness cases (D11, H15) are stale.
- Write required elements per evidence condition, or score the retrieved condition only on what its evidence supports. This was raised by the reviewer in 6 of 14 rows.
- Add fresh held-out cases, since this held-out set has now been studied.
- Show the reviewer the system prompt (with the canary masked) for the canary cases.

## Reproduce

```bash
python -m pytest -q
python eval/run_retrieval.py --split dev --config candidate
python eval/run_generation.py --split heldout --dry-run
python eval/rejudge.py --run eval/results/generation/<run> --judge sonnet --max-usd 2.2   # paid
```

Each run directory holds a `manifest.json` with:
- git commit and dirty flag
- normalized policy hash, plus dataset and fixture hashes
- models, judge settings, rubrics and package versions
- errors

It also holds per-case outputs and scores, and the re-judge manifests record token usage and cost. Embedding scores can differ in the last decimal across hardware and library versions. Model outputs are not deterministic, so a rerun will not reproduce the same answers.
