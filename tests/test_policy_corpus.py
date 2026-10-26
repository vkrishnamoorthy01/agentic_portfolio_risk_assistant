"""Offline checks on the versioned policy corpora (no embedding model needed).

These guard the policy integration: clause numbers, cross-references,
the committed index manifest (passage IDs, token counts, corpus hash), and
that moving from v1 to v2.1 did not change any risk limit.
"""

from __future__ import annotations

import json
import re

import pytest

import retrieval
from retrieval import POLICY_DIR, InvalidQueryError, build_passages, corpus_sha256, parse_clauses, retrieve


def test_v2_has_32_sequential_clause_ids() -> None:
    clauses = parse_clauses("v2.1")

    assert [c.clause_id for c in clauses] == [f"RP{i:02d}" for i in range(1, 33)]
    assert all(c.policy_version == "v2.1" and c.title for c in clauses)


def test_v2_header_states_version_2_1() -> None:
    header = retrieval.POLICY_FILES["v2.1"].read_text(encoding="utf-8").splitlines()[2]

    assert "Version 2.1" in header


def test_every_cross_reference_points_to_an_existing_clause() -> None:
    text = retrieval.POLICY_FILES["v2.1"].read_text(encoding="utf-8")
    referenced = {int(n) for n in re.findall(r"\bRP(\d{2})\b", text)}

    assert referenced <= set(range(1, 33)), sorted(referenced - set(range(1, 33)))


def test_v1_baseline_is_preserved_as_five_sections() -> None:
    clauses = parse_clauses("v1")

    assert [c.clause_id for c in clauses] == ["S1", "S2", "S3", "S4", "S5"]
    assert [p.passage_id for p in build_passages("v1")] == ["S1.p1", "S2.p1", "S3.p1", "S4.p1", "S5.p1"]


@pytest.mark.parametrize("version", ["v1", "v2.1"])
def test_index_manifest_matches_the_policy_and_fits_the_model(version: str) -> None:
    # Rebuild with scripts/build_policy_index.py after editing a policy file.
    manifest = json.loads((POLICY_DIR / f"index_{version}.json").read_text(encoding="utf-8"))

    assert manifest["corpus_sha256"] == corpus_sha256(version), "policy changed; rebuild the index manifest"
    assert [p["passage_id"] for p in manifest["passages"]] == [p.passage_id for p in build_passages(version)]
    too_long = [p for p in manifest["passages"] if p["tokens"] > manifest["max_seq_length"]]
    assert not too_long, f"passages would be silently truncated: {too_long}"


def test_v2_passages_carry_clause_context() -> None:
    passages = build_passages("v2.1")

    assert len(passages) == 98
    assert all(p.embed_text.startswith(f"{p.clause_id} {p.title} (policy v2.1). ") for p in passages)


def _clause_text(version: str, clause_id: str) -> str:
    return next(c.text for c in parse_clauses(version) if c.clause_id == clause_id)


def test_risk_limits_are_unchanged_between_v1_and_v2() -> None:
    # Position > 10% (warning from 8%), volatility Green < 15% / Red > 20%,
    # 99% one-day VaR > 3% of NAV, drawdown beyond 8%: same in both versions.
    assert "exceed 10% of portfolio NAV" in _clause_text("v1", "S1")
    assert "between 8%\nand 10% of NAV is a soft warning" in _clause_text("v1", "S1")
    assert "below 15%" in _clause_text("v1", "S2") and "above 20%" in _clause_text("v1", "S2")
    assert "exceed 3% of portfolio NAV" in _clause_text("v1", "S3")
    assert "beyond 8% from peak" in _clause_text("v1", "S4")

    assert "exceed 10% of portfolio NAV" in _clause_text("v2.1", "RP13")
    assert "From 8% through 10%, including both endpoints, is a soft warning" in _clause_text("v2.1", "RP13")
    assert "Green below 15%" in _clause_text("v2.1", "RP15") and "Red above 20%" in _clause_text("v2.1", "RP15")
    assert "no greater than 3% of portfolio NAV" in _clause_text("v2.1", "RP17")
    assert "beyond 8% from the approved portfolio peak" in _clause_text("v2.1", "RP19")
    escalation = _clause_text("v2.1", "RP25")
    for trigger in ("above 10%", "above 20%", "above 3% of NAV", "below -8%"):
        assert trigger in escalation


def test_the_implementation_appendix_is_not_in_the_retrieval_corpus() -> None:
    corpus_files = {p.name for p in retrieval.POLICY_FILES.values()}

    assert corpus_files == {"risk_policy_v1.md", "risk_policy_v2.md"}
    assert not any("appendix" in p.name.lower() for p in POLICY_DIR.iterdir())


@pytest.mark.parametrize("top_k", [0, 33])
def test_top_k_is_bounded_by_the_clause_count(top_k: int) -> None:
    # Validated before the model is loaded.
    with pytest.raises(InvalidQueryError, match="between 1 and 32"):
        retrieve("volatility", top_k=top_k, version="v2.1")


def _fake_ranking(order: list[str]):  # stands in for the embedding search
    def rank(query: str, version: str = "v2.1", *args, **kwargs) -> list[dict]:
        return [{"clause_id": c, "passage_id": f"{c}.p1", "score": 1.0 - i / 100, "matched_passage": "..."}
                for i, c in enumerate(order)]
    return rank


def test_include_core_puts_the_core_clauses_first_then_the_search(monkeypatch: pytest.MonkeyPatch) -> None:
    others = [f"RP{i:02d}" for i in range(1, 33) if f"RP{i:02d}" not in retrieval.CORE_CLAUSES["v2.1"]]
    # Search ranks the worked examples first and RP19 high, as broad questions tend to.
    order = ["RP29", "RP30", "RP19"] + [c for c in others if c not in ("RP29", "RP30")] + ["RP13", "RP15", "RP17", "RP25"]
    monkeypatch.setattr(retrieval, "rank_clauses", _fake_ranking(order))

    results = retrieve("give me the overall risk picture", top_k=2, version="v2.1", include_core=True)

    assert [r["clause_id"] for r in results] == ["RP13", "RP15", "RP17", "RP19", "RP25", "RP29", "RP30"]
    assert [r["included"] for r in results] == ["core"] * 5 + ["search"] * 2


def test_without_include_core_only_the_search_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval, "rank_clauses", _fake_ranking([f"RP{i:02d}" for i in range(32, 0, -1)]))

    results = retrieve("anything", top_k=2, version="v2.1")

    assert [(r["clause_id"], r["included"]) for r in results] == [("RP32", "search"), ("RP31", "search")]
