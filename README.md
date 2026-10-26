# Agentic Portfolio Risk Assistant

I built this to see, hands-on, what changes between a fixed workflow, an LLM with tools, RAG, an agent and MCP. It's a risk assistant for a 16-stock NSE equity portfolio from an earlier project of mine ([repo](https://github.com/vkrishnamoorthy01/quant_risk_and_trading_portfolio)). It's a proof of concept, kept deliberately small.

**Portfolio:** equal-weighted, ₹1 crore: HDFCBANK, ICICIBANK, SBIN, TCS, INFY, WIPRO, RELIANCE, ONGC, HINDUNILVR, ITC, MARUTI, M&M, SUNPHARMA, DRREDDY, TATASTEEL, ULTRACEMCO.

## How it works

```
Question -> Make.com (V1-V4) or Claude Code via MCP (V5) -> Analytics tool (Python): returns, volatility, VaR, drawdown, concentration
                                                         -> Policy lookup (RAG over a detailed risk policy manual)
         -> answer: the numbers compared with the rules, citing clause numbers from the risk policy manual
```

- **Python does the math; the LLM only explains it.**
- **Prices:** daily closes from IBKR or Kite, or synthetic prices if nothing has been downloaded.
- **Policy lookup:** embedding search (all-MiniLM-L6-v2, in memory, no vector database).
- **Hosting:** the service runs on [Render](https://render.com), and [Make.com](https://www.make.com) calls it there. It can also run locally with [ngrok](https://ngrok.com).
- **Controls:** the assistant can't trade. The policy prescribes human approval and escalation logs, but nothing here enforces them.

## Five versions

| | Setup | What it showed |
|---|---|---|
| V1 | One fixed LLM call in Make | Baseline: an LLM with no data |
| V2 | + Python analytics | The LLM explains numbers it never computes |
| V3 | + policy lookup | Answers can say "breach" and cite the rule |
| V4 | Make AI agent picks the tools | Tool calls follow the question: 0, 1 or 2 calls (4.46, 6.26, 8.87 credits), checked in Make's execution logs |
| V5 | Same tools over MCP in Claude Code | The tools are found automatically, with no hand-written names, descriptions or URLs |

## Key findings

- **The policy lookup is the weak link.** Broad questions ("any serious risk issues?") retrieve worked examples instead of the rules, so the answers come out without thresholds. `include_core=true` always adds the core limit clauses. On the held-out questions, the share with every needed clause rose from 9 of 26 to 16 of 26.
- **Even with the right rules, the LLM makes mistakes.** Haiku 4.5 listed 3.2% VaR as within a 3% limit and called Red volatility a "soft warning".
- **AI judges are lenient.** Sonnet 5.5 passed answers that a review (ChatGPT, checked and lightly edited by me) failed, in 15 of 16 disagreements.
- **Admitting a gap matters.** Asked about sector limits, which neither tool supports, the right answer is to say so, not to invent a limit.
- **Small things break answers.** Percentages sent as fractions (0.0211) printed as "0.0211% of NAV". Every percentage field now carries a `_pct` suffix. Colloquial questions ("is the fund too jumpy?") still miss the volatility rule.

Evaluation details and limitations: [eval/VALIDATION_REPORT.md](eval/VALIDATION_REPORT.md).

## Running it

Python 3.12:

```
pip install -r requirements.txt
```

No API keys are needed, except for the paid answer evaluation (an Anthropic key) and price refreshes (a Kite login or IBKR TWS).

**MCP (V5):** point an MCP host such as Claude Code at this folder. `.mcp.json` registers `analytics/mcp_server.py`, and the host finds `get_portfolio_analytics` and `get_risk_policy_sections` on its own.

**HTTP (V1-V4):**

```
cd analytics
uvicorn service:app --reload
```

- `/analytics`: the portfolio's risk numbers.
- `/policy?query=...`: matching policy clauses. Add `&include_core=true` for overall risk questions.
- Bad input fails loudly: 500 for a missing price, 422 for a bad request.
- The Make scenarios themselves live in Make, not in this repo.

**Prices:** `/analytics?source=` (or `PRICE_SOURCE`) picks `latest` (the default, the newest download), `kite`, `ibkr_paper`, `ibkr_live` or `synthetic`. Every response states its source and date. To download prices, run this with the quant repo's dependencies installed (read-only market data, no orders):

```
python scripts/refresh_prices.py --source ibkr_live      # or ibkr_paper, kite; add --cache-only to skip TWS
```

Downloads are gitignored. On Render, upload them as secret files and set `PRICE_DATA_DIR=/etc/secrets`.

**Docker:**

```
docker build -t portfolio-risk-service .
docker run --rm -p 8000:8000 --memory=512m portfolio-risk-service
python scripts/smoke_test.py http://localhost:8000
```

**Tests and deployment:** `python -m pytest tests` runs offline. GitHub Actions runs the tests, then builds the image and smoke-tests it under 512 MB. Render (`render.yaml`) redeploys `main` only after those checks pass.

---

*Code, tests and docs were drafted with AI tools in the loop (Claude Code, Sonnet 5, OpenAI Codex, GPT-6 Astra). The modeling choices and judgment calls are mine, and so are the errors.*
