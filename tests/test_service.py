"""Endpoint tests for analytics/service.py through FastAPI's test client.

Retrieval is replaced with a stub, so these run without sentence-transformers
or PyTorch (and in CI). The real model is exercised by the Docker smoke test
(scripts/smoke_test.py), which runs against the built container.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import prices
import service

MOCK_PRICES = Path(__file__).resolve().parent.parent / "data" / "mock_prices.csv"


@pytest.fixture
def data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A price folder holding only the synthetic file, so results don't depend on local downloads."""
    shutil.copy(MOCK_PRICES, tmp_path / "mock_prices.csv")
    monkeypatch.setattr(prices, "DATA_DIR", tmp_path)
    monkeypatch.delenv("PRICE_SOURCE", raising=False)
    return tmp_path


def add_download(data_dir: Path, source: str, last_session: str) -> None:
    """A fake refresh_prices.py output: the synthetic prices cut at last_session."""
    frame = pd.read_csv(MOCK_PRICES)
    frame[frame["date"] <= last_session].to_csv(data_dir / f"prices_{source}.csv", index=False)
    meta = {"source": source, "description": f"test {source}", "last_session": last_session,
            "built_utc": "2026-10-26T00:00:00Z", "cache_only": True}
    (data_dir / f"prices_{source}.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> TestClient:
    def _stub_retrieve(query: str, top_k: int = 2) -> list[dict]:
        return [{"section": f"stub {i + 1}", "text": "stub text", "score": 1.0 - i / 10} for i in range(top_k)]

    monkeypatch.setattr(service, "retrieve", _stub_retrieve)
    return TestClient(service.app)


def test_importing_the_service_does_not_load_the_embedding_model() -> None:
    assert "sentence_transformers" not in sys.modules


def test_health(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "commit": "local"}


def test_health_reports_the_deployed_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "36669c5abc")

    assert client.get("/health").json()["commit"] == "36669c5abc"


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
    assert "refresh_prices.py" in body["data_note"]  # tells the user how to get market prices
    assert body["downloaded_sources"] == {}


def test_latest_uses_the_most_recent_download(client: TestClient, data_dir: Path) -> None:
    add_download(data_dir, "kite", "2026-09-10")
    add_download(data_dir, "ibkr_paper", "2026-09-11")

    body = client.get("/analytics").json()

    assert body["requested_source"] == "latest"
    assert body["data_source"] == "ibkr_paper"
    assert body["as_of"] == "2026-09-11"
    assert body["downloaded_sources"] == {"kite": "2026-09-10", "ibkr_paper": "2026-09-11"}
    assert "Nothing was fetched" in body["data_note"]


def test_latest_prefers_ibkr_live_on_the_same_session(client: TestClient, data_dir: Path) -> None:
    for source in ("kite", "ibkr_paper", "ibkr_live"):
        add_download(data_dir, source, "2026-09-11")

    assert client.get("/analytics").json()["data_source"] == "ibkr_live"


def test_a_named_source_is_used_even_if_older(client: TestClient, data_dir: Path) -> None:
    add_download(data_dir, "kite", "2026-09-10")
    add_download(data_dir, "ibkr_live", "2026-09-11")

    body = client.get("/analytics", params={"source": "kite"}).json()

    assert (body["data_source"], body["as_of"]) == ("kite", "2026-09-10")


def test_price_source_variable_sets_the_default(client: TestClient, data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    add_download(data_dir, "ibkr_live", "2026-09-11")
    monkeypatch.setenv("PRICE_SOURCE", "synthetic")

    assert client.get("/analytics").json()["data_source"] == "synthetic"


@pytest.mark.parametrize("source", ["ibkr_live", "yahoo"])
def test_a_source_that_is_not_downloaded_or_unknown_is_rejected(client: TestClient, source: str) -> None:
    response = client.get("/analytics", params={"source": source})

    assert response.status_code == 422
    assert source in response.json()["detail"]


def test_analytics_fails_loudly_on_a_missing_price(client: TestClient, data_dir: Path) -> None:
    frame = pd.read_csv(MOCK_PRICES)
    frame.loc[100, "TCS"] = None
    frame.to_csv(data_dir / "mock_prices.csv", index=False)

    response = client.get("/analytics")

    assert response.status_code == 500
    assert "TCS" in response.json()["detail"]


def test_analytics_fails_loudly_on_a_missing_ticker(client: TestClient, data_dir: Path) -> None:
    pd.read_csv(MOCK_PRICES).drop(columns=["ITC"]).to_csv(data_dir / "mock_prices.csv", index=False)

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
        {"query": "volatility", "top_k": 33},  # policy v2.1 has 32 clauses
    ],
)
def test_policy_rejects_invalid_requests(client: TestClient, params: dict) -> None:
    assert client.get("/policy", params=params).status_code == 422
