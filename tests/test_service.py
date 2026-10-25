"""Endpoint tests for analytics/service.py through FastAPI's test client.

Retrieval is replaced with a stub, so these run without sentence-transformers
or PyTorch (and in CI). The real model is exercised by the Docker smoke test
(scripts/smoke_test.py), which runs against the built container.
"""

from __future__ import annotations

import sys

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import service


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    def _stub_retrieve(query: str, top_k: int = 2) -> list[dict]:
        return [{"section": f"stub {i + 1}", "text": "stub text", "score": 1.0 - i / 10} for i in range(top_k)]

    monkeypatch.setattr(service, "retrieve", _stub_retrieve)
    return TestClient(service.app)


def test_importing_the_service_does_not_load_the_embedding_model() -> None:
    assert "sentence_transformers" not in sys.modules


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analytics_reproduces_the_independently_checked_numbers(client: TestClient) -> None:
    # Recalculated independently from data/mock_prices.csv during the project review.
    body = client.get("/analytics").json()

    assert body["as_of"] == "2026-09-11"
    assert body["vol_20d_annualized_pct"] == 22.88
    assert body["historical_var_99_1d"]["pct_of_nav_pct"] == 2.11
    assert body["drawdown_from_peak_pct"] == -22.48
    assert body["largest_position_pct"] == 6.25
    assert len(body["individual_returns_1d_pct"]) == 16


def test_analytics_labels_the_data_as_synthetic_and_dated(client: TestClient) -> None:
    body = client.get("/analytics").json()

    assert body["data_source"] == "synthetic"
    assert "not market data" in body["data_note"]


def test_analytics_fails_loudly_on_a_missing_price(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    prices = pd.read_csv(service.DATA_PATH)
    prices.loc[100, "TCS"] = None
    broken = tmp_path / "prices.csv"
    prices.to_csv(broken, index=False)
    monkeypatch.setattr(service, "DATA_PATH", broken)

    response = client.get("/analytics")

    assert response.status_code == 500
    assert "TCS" in response.json()["detail"]


def test_analytics_fails_loudly_on_a_missing_ticker(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    broken = tmp_path / "prices.csv"
    pd.read_csv(service.DATA_PATH).drop(columns=["ITC"]).to_csv(broken, index=False)
    monkeypatch.setattr(service, "DATA_PATH", broken)

    response = client.get("/analytics")

    assert response.status_code == 500
    assert "ITC" in response.json()["detail"]


def test_policy_returns_the_requested_number_of_sections(client: TestClient) -> None:
    response = client.get("/policy", params={"query": "volatility limit", "top_k": 3})

    assert response.status_code == 200
    assert len(response.json()["results"]) == 3


@pytest.mark.parametrize(
    "params",
    [
        {},  # no query
        {"query": ""},
        {"query": "x" * 501},
        {"query": "volatility", "top_k": 0},
        {"query": "volatility", "top_k": 6},  # the policy has 5 sections
    ],
)
def test_policy_rejects_invalid_requests(client: TestClient, params: dict) -> None:
    assert client.get("/policy", params=params).status_code == 422
