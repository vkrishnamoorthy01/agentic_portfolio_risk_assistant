"""Offline checks on the golden evaluation dataset (no model, no network).

They keep the dataset internally consistent and the held-out split frozen:
any edit to cases_heldout.json after the freeze fails this test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from retrieval import parse_clauses

DATASET = Path(__file__).resolve().parent.parent / "eval" / "dataset"
FIELDS = {"case_id", "category", "intended_use", "fixture", "question", "required_clauses", "supporting_clauses",
          "expected_tools", "required_elements", "forbidden_claims", "criteria", "derived_from_manual_example",
          "reference_status"}
TOOLS = {"get_portfolio_analytics", "get_risk_policy_sections"}


def _load(name: str) -> dict:
    return json.loads((DATASET / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return _load("cases_dev.json")["cases"] + _load("cases_heldout.json")["cases"]


def test_case_count_and_unique_ids(cases: list[dict]) -> None:
    ids = [c["case_id"] for c in cases]

    assert 40 <= len(cases) <= 50
    assert len(set(ids)) == len(ids)


def test_every_case_has_the_required_fields(cases: list[dict]) -> None:
    for case in cases:
        assert FIELDS <= set(case), (case["case_id"], FIELDS - set(case))
        assert case["question"].strip() and case["criteria"].strip()
        assert set(case["expected_tools"]) <= TOOLS


def test_clause_ids_fixtures_and_injections_exist(cases: list[dict]) -> None:
    clause_ids = {c.clause_id for c in parse_clauses("v2.1")}
    fixtures = _load("fixtures.json")
    for case in cases:
        assert set(case["required_clauses"]) | set(case["supporting_clauses"]) <= clause_ids, case["case_id"]
        assert not set(case["required_clauses"]) & set(case["supporting_clauses"]), case["case_id"]
        assert case["fixture"] is None or case["fixture"] in fixtures["fixtures"], case["case_id"]
        assert case.get("injected_passage") is None or case["injected_passage"] in fixtures["injected_passages"]


def test_no_reference_is_labelled_human_reviewed(cases: list[dict]) -> None:
    assert {c["reference_status"] for c in cases} == {"ai_drafted_unreviewed"}


def test_heldout_cases_are_not_derived_from_the_manual_examples() -> None:
    heldout = _load("cases_heldout.json")["cases"]

    assert not any(c["derived_from_manual_example"] for c in heldout)
    # RP29/RP30 worked-example figures must not reappear in held-out questions.
    for figure in ("7.20%", "22.40%", "2.60%", "-11.30%", "12% holding", "-4.00%", "-9.00%"):
        assert not any(figure in c["question"] for c in heldout), figure


def test_heldout_split_matches_its_freeze_record() -> None:
    freeze = _load("FREEZE.json")
    for name, digest in freeze["sha256"].items():
        assert hashlib.sha256((DATASET / name).read_bytes()).hexdigest() == digest, f"{name} changed after freeze"
