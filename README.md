# Agentic Portfolio Risk Assistant

I built this to see, hands-on, what differs between a deterministic workflow, an LLM with tool-calling, an agentic system, RAG, and MCP. It's built around a Portfolio Risk Analyst agent for a 16-stock NSE equity portfolio I built earlier ([repo](https://github.com/vkrishnamoorthy01/quant_risk_and_trading_portfolio)).

Scope, tools, and infra are deliberately minimal. Should be viewed as a proof-of-concept.

## Portfolio

Equal-weighted, ₹1 crore notional: HDFCBANK, ICICIBANK, SBIN, TCS, INFY, WIPRO, RELIANCE, ONGC, HINDUNILVR, ITC, MARUTI, M&M, SUNPHARMA, DRREDDY, TATASTEEL, ULTRACEMCO. Same universe as `risk_project` in `quant_risk_and_trading_portfolio`; I ported the VaR/analytics logic from there.

## Architecture

```
User -> Make.com (orchestrator) -> Portfolio Analytics tool (Python, deterministic)
                                 -> Risk Policy RAG (embeddings over a short policy doc)
     -> synthesized risk assessment -> human approval for any consequential action
```

The human-approval step and the escalation logging in the risk policy (`policy/risk_policy_v2.md`) are controls the policy prescribes. Nothing in this repo enforces them: no approval gate, no escalation log. The assistant only reads numbers and policy text; it can't trade.


- **Market data**: daily closes for the 16 tickers from Kite, IBKR paper or IBKR live (downloaded by `scripts/refresh_prices.py`), or synthetic prices (`data/generate_mock_data.py`) where nothing has been downloaded.
- **Analytics tool**: Python service ported from `risk_project`, exposing deterministic calculations (returns, vol, contributors, concentration, historical VaR) over HTTP. The LLM never does the arithmetic itself.
- **RAG**: a short fictional risk policy document, retrieved via real embedding and cosine-similarity search, no vector DB needed at this scale.
- **Orchestrator**: Make.com (free plan). V1 uses a fixed scenario; V4 swaps in Make's AI Agent module so the LLM decides which tools to call.
- **Local hosting**: the Python service runs locally, tunneled to Make via ngrok (free).
- **MCP (V5)**: `analytics/mcp_server.py` wraps the same `get_analytics`/`retrieve` logic as MCP tools over stdio, registered via `.mcp.json`. Host/client is Claude Code itself, so no ngrok or cloud infra needed.

## Running it

Needs Python 3.11+ and pip. Install deps:

```
pip install -r requirements.txt
```


No API keys needed for anything in this repo. Mock price data (`data/mock_prices.csv`) is already checked in; regenerate with `python data/generate_mock_data.py` if needed (fixed seed, so reproducible output).

**MCP path (V5, easiest to try locally):** point an MCP host (I built and tested against Claude Code) at this project directory. `.mcp.json` registers `analytics/mcp_server.py` as a stdio server; the host discovers `get_portfolio_analytics` and `get_risk_policy_sections` on its own.

**HTTP path (V1-V4):**

```
cd analytics
uvicorn service:app --reload
```


Then hit `http://localhost:8000/analytics` or `http://localhost:8000/policy?query=...` directly. Wiring this into Make.com the way V1-V4 do also needs an ngrok tunnel and a Make scenario with an Anthropic API key configured in Make's UI. Both live outside this repo, so they're not reproducible just by cloning it.

**Price data.** `/analytics?source=` (or the `PRICE_SOURCE` variable) picks the prices:

| Source | What it reads |
|---|---|
| `latest` (default) | the most recent download; synthetic only if nothing has been downloaded |
| `kite`, `ibkr_paper`, `ibkr_live` | `data/prices_<source>.csv`, written by `scripts/refresh_prices.py` |
| `synthetic` | `data/mock_prices.csv` (generated, not market data) |

Nothing is downloaded while serving a request: Kite needs a daily login and IBKR needs TWS running. To get the newest prices, run the refresh yourself, using the quant repo's price code (`QUANT_REPO`, default `D:\Personal_projects\quant_risk_and_trading_portfolio`) in an environment with its dependencies (`personal_projects`):

```
python scripts/refresh_prices.py --source ibkr_live               # TWS live, port 7496
python scripts/refresh_prices.py --source ibkr_paper              # TWS paper, port 7497
python scripts/refresh_prices.py --source kite                    # Kite login
python scripts/refresh_prices.py --source ibkr_live --cache-only  # IBKR bars already stored, no connection
```

Market data only; nothing places orders. The downloads are gitignored, so Docker and CI serve synthetic prices. On Render, upload `prices_<source>.csv` and `prices_<source>.json` as secret files and set `PRICE_DATA_DIR=/etc/secrets`; re-upload them after each refresh. Every response names its source (`data_source`), its last session (`as_of`), what is downloaded (`downloaded_sources`), and in `data_note` how to fetch newer prices. Bad inputs fail loudly instead of producing a number: a missing price or ticker returns a 500 with the reason, and an empty, overlong (over 500 characters) or out-of-range `/policy` request returns a 422.

**Docker:**

```
docker build -t portfolio-risk-service .
docker run --rm -p 8000:8000 --memory=512m portfolio-risk-service
python scripts/smoke_test.py http://localhost:8000
```

The image (`Dockerfile`, pinned dependencies in `requirements-service.txt`) installs CPU-only PyTorch and downloads the embedding model at build time, so the container makes no network calls at runtime. It loads the model at startup (about 10 seconds), runs as a non-root user, and listens on `$PORT` (8000 by default). Make.com, ngrok and the LLM stay outside it.

**Tests and CI:** `python -m pytest tests -v` runs the unit and endpoint tests (retrieval is stubbed, so no model download). GitHub Actions (`.github/workflows/tests.yml`) runs them on every push and pull request, then builds the image, starts it under a 512 MB memory cap and runs `scripts/smoke_test.py` against it, with the real model.

**Deployment (Render, free tier):** `render.yaml` defines the service as a Render Blueprint. In Render: **New > Blueprint**, pick this repo, apply. Render builds the Dockerfile, checks `/health`, and redeploys each new commit on `main` only after its GitHub checks pass (`autoDeployTrigger: checksPass`). Free instances sleep after 15 minutes idle and take about a minute to wake. Verify a deployment with `python scripts/smoke_test.py https://<service>.onrender.com`.

**Policy v2.1 and evaluation:** the retrieval corpus is now policy v2.1 (`policy/risk_policy_v2.md`, 32 clauses RP01-RP32), embedded as paragraph passages so no passage exceeds the model's 256-token limit; the original 5-section policy is kept as `policy/risk_policy_v1.md` (`POLICY_VERSION=v1`). `eval/` holds a 50-case golden dataset (dev and frozen held-out), a retrieval evaluation, a generation-evaluation harness (DeepEval, not yet run; paid calls need `requirements-eval.txt` and an API key) and a manual-review sheet. Results and what is still pending: `eval/VALIDATION_REPORT.md`.

## Status

- [x] V1 step 1: project scaffold + synthetic 16-stock daily price data (`data/mock_prices.csv`, 260 trading days)
- [x] V1: bare Make scenario, one fixed LLM call (Webhooks > Custom webhook -> Anthropic Claude "Simple Text Prompt" -> Webhooks > Webhook response). Working end-to-end.
- [x] V2: `analytics/service.py` FastAPI app ported from `risk_project`, exposing `GET /analytics` (portfolio return, 20-day vol, 99% historical VaR, drawdown, concentration, top contributors/detractors, individual returns, all percentage fields pre-scaled with `_pct` suffixes), tunneled via ngrok, wired into the Make scenario. Working end-to-end, verified against live output.
- [x] V3: `policy/risk_policy.md` (now kept as `policy/risk_policy_v1.md`) drafted and `analytics/retrieval.py` built: chunking (split on `## ` headers) + local embeddings (`sentence-transformers`, `all-MiniLM-L6-v2`) + in-memory cosine-similarity search, exposed as `GET /policy?query=...`. Claude now explicitly states breach/no-breach per policy section (verified live: correctly flagged volatility as RED-breach and VaR as compliant, citing the right sections).
- [x] V4: separate Make scenario `Agentic_portfolio_risk_assistant_v4`. Webhooks -> Make AI Agent (Claude Haiku 4.5; two tools: `get_portfolio_analytics`, `get_risk_policy_sections`) -> Webhooks. Verified end-to-end with three tool-selective questions, see below.
- [x] V5: `analytics/mcp_server.py`, same logic exposed as two MCP tools over stdio, registered via `.mcp.json`, consumed by Claude Code. Tool discovery happened automatically and invocation worked live in-conversation, see below.

## V4: agentic tool selection vs. V1-V3's fixed sequence

Verified via Make's execution-log trace, not inferred from the answer text.

| Question | Tools called | Agent credits | What it shows |
|---|---|---|---|
| "What is my largest position?" | `get_portfolio_analytics` only | 6.26 | recognized it needed live numbers, not policy |
| "What does VaR mean?" | none | 4.46 | recognized a pure knowledge question |
| "Are there any serious risk issues in my portfolio today?" | `get_portfolio_analytics` -> `get_risk_policy_sections` | 8.87 | got numbers first, then checked them against policy limits |

For the third question, the agent correctly classified 20-day volatility as a RED-zone policy breach (22.88% vs. the 20% threshold) while confirming concentration and VaR were within limits, a genuine breach determination the fixed V1-V3 pipeline never had to make itself. `_v3` always calls both tools in the same fixed order regardless of the question (tool output computed at call time from the synthetic dataset, but a deterministic workflow); `_v4`'s tool-call count and sequence change based on what the question needs (0, 1, or 2 calls), and credit cost scales with that (4.46 -> 6.26 -> 8.87).

A later recheck of the same snapshot: drawdown from peak is -22.48%, beyond the policy's 8% threshold (Section 4), which also triggers escalation (Section 5), and the answer above doesn't mention it. Whether the agent missed it can't be settled without its saved response and retrieved passages, so it is an open case for the evaluation milestone, not a verified result either way.

## V5: MCP vs. direct HTTP wiring

`analytics/mcp_server.py` exposes the same two capabilities as V1-V4's HTTP endpoints, over MCP instead of raw HTTP, importing the same underlying functions rather than duplicating them. Claude Code is both the MCP host and client here; `mcp_server.py` runs as a local subprocess over stdio. No network, no ngrok, no cloud infra, unlike every prior stage.

**What MCP added over Make's direct HTTP wiring, concretely:**
- **Discovery.** Pointing Claude Code at the project folder was enough for it to find and load both tools automatically from the server's decorators and docstrings, no hand-typed tool name, description, or URL. In V4, every tool needed a manually written name, description, and URL inside Make's UI, kept in sync by hand.
- **Invocation.** I asked "Am I overweighted on any sector? Does it breach policy limits? Should I be concerned about concentration risk?", and Claude Code called both tools on its own, the same class of tool-selection decision as V4's Make Agent, over a different transport.

**A genuine finding, not staged:** neither tool actually supports sector-level analysis. The analytics tool only returns per-stock weights, and the policy document only defines a per-position limit, no sector rule. The correct answer had to admit that gap rather than invent a sector limit that doesn't exist, while still computing sector totals as plain arithmetic on the weights already returned, clearly labeled as not tool-verified. A real instance of the guardrail failure this project set out to explore, caught in normal use rather than engineered as a test.

## Notable bugs and lessons

**Percentage/unit-conversion bug (V2, 2026-09-12).** `analytics/service.py` originally returned percentage fields as raw fractions (`0.0211` for 2.11%). The Make prompt had `% of NAV` hardcoded right after the VaR fraction, so it rendered as "0.0211% of NAV" instead of "2.11% of NAV". Three other fields in the same prompt had no `%` hardcoded, and Claude happened to correctly infer a ×100 conversion for those, so the prompt was right 3 times out of 4, by luck, not design. Fix: moved the conversion into `service.py`. Every percentage field is now pre-scaled with an explicit `_pct` suffix, so appending a literal `%` in the prompt is always correct, no inference needed.

**Retrieval-quality finding (V3, 2026-09-12).** With only 5 short, initially similar policy chunks, the small local embedding model (`all-MiniLM-L6-v2`) struggled to tell them apart. The query "is the portfolio too volatile" ranked the actual Volatility Thresholds section 3rd out of 5. Fix (partial): rewrote the policy doc so escalation instructions live only in one section, leaving the others more topically distinct vocabulary. That fixed the direct case. What didn't get fixed: "is the fund too jumpy right now" still ranks Volatility Thresholds last, the real ceiling of a small, free, local embedding model on colloquial phrasing. Kept as-is as a genuine, reproducible retrieval-failure case study rather than papered over.

**Make array-mapping quirk (V3, 2026-09-12).** Make's field-picker only offers a flattened preview for an array field like `/policy`'s `results`, so clicking doesn't cleanly grab a single item. Fix: type the reference directly using Make's 1-based bracket syntax, `{{8.data.results[1].text}}`.

---

*This project's code, tests, and documentation were drafted with AI tools in the loop, including Claude Code, Sonnet 5, OpenAI Codex, and GPT-6 Astra. The modeling choices and judgment calls are mine, and so are the errors.*
