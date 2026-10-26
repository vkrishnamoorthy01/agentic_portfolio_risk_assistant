"""Offline checks for the generation harness and review sheet (no model downloads, no API calls)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))
sys.path.insert(0, str(ROOT / "analytics"))

import make_review_sheet  # noqa: E402
import retrieval  # noqa: E402
import run_generation  # noqa: E402


def test_reference_evidence_contains_required_clauses_and_injected_text() -> None:
    data, fixtures, injected = run_generation.load_split("dev")
    clauses = {c.clause_id: c for c in retrieval.parse_clauses("v2.1")}
    case = next(c for c in data["cases"] if c["case_id"] == "D18")
    evidence = run_generation.evidence_for(case, "reference", clauses, injected)
    ids = [e["id"] for e in evidence]
    assert set(case["required_clauses"]) <= set(ids)
    assert "INJECTED-1" in ids
    message = run_generation.user_message(case, evidence, fixtures)
    assert "injected" not in message.lower()  # the model is not told which passage is fake
    assert run_generation.CANARY not in message


def test_fixture_is_passed_as_analytics_output() -> None:
    data, fixtures, injected = run_generation.load_split("dev")
    case = next(c for c in data["cases"] if c["fixture"] == "F7_var_unavailable")
    message = run_generation.user_message(case, [], fixtures)
    assert "get_portfolio_analytics" in message and '"historical_var_99_1d": null' in message
    assert "hypothetical_variant" not in message


def test_deterministic_checks() -> None:
    case = {"required_clauses": ["RP13", "RP25"]}
    checks = run_generation.deterministic_checks(case, f"Per RP13 this is a breach (RP99). Token {run_generation.CANARY}")
    assert checks["canary_leaked"]
    assert checks["required_not_cited"] == ["RP25"] and not checks["all_required_cited"]
    assert checks["invalid_clause_ids"] == ["RP99"]


def test_review_cases_are_heldout_and_judge_free() -> None:
    cases = make_review_sheet.load_cases("heldout")
    assert 12 <= len(make_review_sheet.REVIEW_CASES) <= 15
    assert set(make_review_sheet.REVIEW_CASES) <= set(cases)
    assert not any("judge" in d or "score" in d for d in make_review_sheet.DIMENSIONS)


def test_review_sheet_uses_the_injected_labels_the_model_saw() -> None:
    assert make_review_sheet.INJECTED_DISPLAY_IDS == run_generation.INJECTED_DISPLAY_IDS
