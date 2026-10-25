# Validation report: policy v2.1 integration and evaluation

Branch `policy-v2-eval` (local, not pushed). Date 2026-10-25. Scope: the policy retrieval component of the Portfolio Risk Assistant, and a prepared (not yet run) answer-quality evaluation. Nothing here measures the Make.com v3/v4 scenarios end to end, tool selection, or production readiness.

## 1. Implemented

- **Versioned policy corpus.** `policy/risk_policy_v1.md` (the original 5 sections, kept as the baseline) and `policy/risk_policy_v2.md` (v2.1, 32 clauses RP01-RP32). `POLICY_VERSION` selects one; v2.1 is the default. The implementation appendix is not in the corpus.
- **Clause-aware passages.** v2.1 is embedded as 98 paragraph passages, each prefixed with clause ID, title and policy version. Clauses are ranked by their best passage and returned whole, so a limit is never split from its exceptions.
- **Truncation guard.** Building the index raises `PassageTooLongError` if any passage exceeds the model's 256-token limit. Committed manifests (`policy/index_v1.json`, `policy/index_v2.1.json`) record every passage's token count and a line-ending-normalized corpus hash.
- **Same retrieval stack.** all-MiniLM-L6-v2, in-memory cosine similarity. No vector database. Risk limits and calculation methods unchanged (a test compares v1 and v2.1 thresholds).
- **Golden dataset** `golden-v1`: 50 cases, 22 dev and 28 held-out, frozen in `eval/dataset/FREEZE.json` before any tuning. Every reference answer was drafted by an AI and is marked `ai_drafted_unreviewed`. None has been independently reviewed. Dev cases built from the manual's worked examples are flagged; held-out has none.
- **Retrieval evaluation** `eval/run_retrieval.py`.
- **Generation evaluation harness** `eval/run_generation.py`: DeepEval (Faithfulness and GEval rubrics), two evidence conditions, a synthetic canary, deterministic checks. It has a dry-run mode that makes no network calls.
- **Blinded review sheet** `eval/make_review_sheet.py` and `eval/manual_review/README.md`.
- **Tests**: 45 offline tests. CI needs no API key and makes no paid calls.

Why DeepEval rather than Ragas: the questions that matter here are policy-specific (correct band and inclusivity, abstention on missing inputs, resisting injected limits). GEval takes custom rubrics for these directly, and DeepEval also has Faithfulness. Ragas centers on generic RAG metrics and would need custom metrics for most of this.

## 2. Actually executed

| Run | Calls | Saved under |
|---|---|---|
| Retrieval, dev, baseline and candidate | local only | `eval/results/retrieval/dev_*` |
| Retrieval, held-out, baseline and candidate, once each | local only | `eval/results/retrieval/heldout_*` |
| Generation dry run, dev and held-out | none | `eval/results/generation/*_dryrun_*` |
| Test suite | local only | 45 passed |

Not executed: any generation or judge call, any manual review.

## 3. Verified by saved evidence

### Truncation
Whole v2.1 clauses: 4 of 32 (13%) exceed 256 tokens (RP03 258, RP25 276, RP29 264, RP32 396). Embedded whole, their ends would be dropped silently. For RP25 Escalation, that is the record-keeping paragraph. Paragraph passages: 0 of 98 exceed the limit. The longest is 124 tokens.

### Retrieval (clause level)
Definitions: a case's required clauses are the relevant set. `complete@k` = all required clauses in the top k. Cases with no required clauses are excluded (dev 1 of 22; held-out 2 of 28) and listed in each summary. Scores are cosine similarities used for ranking. They are not probabilities. Baseline = whole clauses (pre-v2 chunking, 4 truncated). Candidate = paragraph passages, now the service default. The service returns **k = 2**.

| Split | Config | complete@2 | complete@5 | Multi-clause complete@2 | Multi-clause complete@5 | MRR |
|---|---|---|---|---|---|---|
| dev (21) | baseline | 9/21 (43%) | 14/21 (67%) | 0/8 (0%) | 2/8 (25%) | 0.648 |
| dev (21) | candidate | 9/21 (43%) | 14/21 (67%) | 0/8 (0%) | 2/8 (25%) | 0.686 |
| held-out (26) | baseline | 5/26 (19%) | 13/26 (50%) | 0/17 (0%) | 6/17 (35%) | 0.746 |
| held-out (26) | candidate | 9/26 (35%) | 11/26 (42%) | 3/17 (18%) | 5/17 (29%) | 0.743 |

At the service's k = 2, the candidate completes more held-out cases than the baseline: 9 vs 5. At k = 5 it completes fewer: 11 vs 13. The candidate was adopted because it removes truncation, not because it retrieves better. On held-out it is not consistently better.

Failure patterns, from the per-case files:
- **Single-clause questions in policy vocabulary mostly succeed.** Held-out direct 2/2 and paraphrase 3/3 at k = 5.
- **Multi-clause answers rarely arrive complete.** At k = 2, 3 of 17 held-out multi-clause cases (18%) are complete.
- **Evidence implied by the tool output is not retrievable from the question.** Examples: RP10 missing inputs at rank 26 (H17), RP09 freshness at rank 15 (H15), RP28 untrusted content at rank 29-32 (H21, H22, H24), RP13 position at rank 27 when the question is "does anything need escalating?" (H13).
- **Overall and escalation questions miss the core limit clauses.** H12 (all four breached): RP13 rank 32, RP19 rank 25. H14 overall: RP19 rank 26.
- **Injected passages are retrieved.** In 2 of 2 injected cases, the injected passage reached the top 2 handed to the model. D18 was rank 1. H22 was rank 1 (baseline) and rank 2 (candidate). Defense therefore depends on the answering step, which is not yet measured.

### Generation plan (dry run only)
100 prompts in all: 50 cases × 2 conditions, 44 dev and 56 held-out. Answers are generated by direct Messages API calls, with the analytics fixture supplied as tool output. This is **component evaluation**: Make.com is bypassed and the model chooses no tools.

## 4. Pending

| Item | Blocked on |
|---|---|
| Generation + judge run on dev, then once on held-out | your authorization of cost and models |
| DeepEval wrapper and judge prompt check (one-case smoke run) | the same authorization; `requirements-eval.txt` is not installed yet |
| Manual review of 14 held-out answers | generated answers, then your scores |
| Judge-vs-human agreement | your scores |
| Tool-selection evaluation | saved Make.com tool traces (none in the repo) |
| Independent review of reference answers | a reviewer other than the drafting AI |
| Retrieval change (see below) | your decision; would be tuned on dev, then scored once on held-out |

The retrieval change that the evidence supports, though it was not tested: for portfolio and overall questions, always include the core limit clauses (RP13, RP15, RP17, RP19, RP25 and RP08-RP10), and use semantic search only for the remainder. Raising top_k alone helps less, as complete@5 is still 42-50% on held-out.

## Reproduce

```bash
python -m pytest -q
python eval/run_retrieval.py --split dev --config candidate
python eval/run_generation.py --split heldout --dry-run
```

Each run directory holds a `manifest.json` with: git commit and dirty flag, normalized policy hash, dataset and fixture hashes, model, chunking and package versions. It also holds per-case results and a summary. Embedding scores can differ in the last decimal across hardware and library versions.
