"""Smoke-test a running instance of the HTTP service: local container or deployed URL.

    python scripts/smoke_test.py http://localhost:8000
    python scripts/smoke_test.py https://<your-service>.onrender.com

Checks /health, the /analytics numbers and labels, a real /policy retrieval
(the embedding model, not a stub), and that a blank query is rejected.
Standard library only, so it runs anywhere. Exits non-zero on any failure.
"""

from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen


def get(base: str, path: str, params: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    url = f"{base.rstrip('/')}{path}" + (f"?{urlencode(params)}" if params else "")
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def check(label: str, condition: bool, detail: object = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}  {detail}")
    if not condition:
        raise SystemExit(1)


def main(base: str) -> None:
    started = time.perf_counter()
    status, body = get(base, "/health")
    check("GET /health", status == 200 and body.get("status") == "ok",
          f"commit={body.get('commit')} ({time.perf_counter() - started:.1f}s)")

    status, body = get(base, "/analytics")
    check("GET /analytics status", status == 200, status)
    source = body.get("data_source")
    check("analytics names its price source", source in ("synthetic", "kite", "ibkr_paper", "ibkr_live"), source)
    check("analytics as_of present", bool(body.get("as_of")), body.get("as_of"))
    if source == "synthetic":  # the container and CI have no downloaded prices; the synthetic numbers are known
        check("analytics as_of", body.get("as_of") == "2026-09-11", body.get("as_of"))
        check("99% VaR % of NAV", body["historical_var_99_1d"]["pct_of_nav_pct"] == 2.11, body["historical_var_99_1d"])
        check("20-day volatility %", body["vol_20d_annualized_pct"] == 22.88, body["vol_20d_annualized_pct"])
        check("drawdown %", body["drawdown_from_peak_pct"] == -22.48, body["drawdown_from_peak_pct"])

    status, body = get(base, "/policy", {"query": "drawdown threshold from peak NAV", "top_k": 2})
    sections = [r["section"] for r in body.get("results", [])]
    # Policy v2.1 (clause RP19) on new deployments; older deployments serve the v1 headings.
    expected = {"v2.1": "RP19 Drawdown Threshold"}.get(body.get("policy_version"), "4. Drawdown Threshold")
    check("GET /policy real retrieval", status == 200 and sections[:1] == [expected],
          f"policy {body.get('policy_version', 'v1')}: {sections}")

    if body.get("policy_version") == "v2.1":
        status, body = get(base, "/policy", {"query": "give me the overall risk picture", "include_core": "true"})
        ids = [r["clause_id"] for r in body.get("results", [])]
        check("GET /policy include_core", status == 200 and ids[:5] == ["RP13", "RP15", "RP17", "RP19", "RP25"], ids)

    status, _ = get(base, "/policy", {"query": ""})
    check("blank policy query rejected", status == 422, status)
    print(f"All checks passed in {time.perf_counter() - started:.1f}s against {base}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
