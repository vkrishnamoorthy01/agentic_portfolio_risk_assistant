"""MCP server exposing the same portfolio risk tools as service.py's HTTP API.

Same underlying logic (service.py, retrieval.py), a different transport.
Compare this file against how these tools had to be wired into Make in
V1-V4: there, each tool needed a hand-typed URL, HTTP method, and a
hand-written tool-description string inside Make's UI before an agent
could use it. Here, an MCP host discovers the tool's name, arguments, and
purpose directly from this file's decorators/type hints/docstrings, no
separate description to keep in sync, no URL to copy-paste.

Run directly for a quick manual check: `python mcp_server.py`
Run as an MCP server (stdio transport, the default): registered via
.mcp.json and started automatically by an MCP host such as Claude Code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.mcpserver import MCPServer

from retrieval import retrieve
from service import get_analytics

mcp = MCPServer("portfolio-risk-tools")


@mcp.tool()
def get_portfolio_analytics(source: str = "latest") -> dict:
    """Get portfolio risk analytics for the 16-stock NSE equal-weighted
    portfolio as of the last session in the chosen price data (the "as_of"
    field): 1-day return, 20-day annualized volatility, 99% one-day
    historical VaR, drawdown from peak, largest position (concentration),
    and top contributors/detractors.

    source: "latest" (default, the most recently downloaded prices),
    "kite", "ibkr_paper", "ibkr_live", or "synthetic" (generated, not
    market data). Nothing is downloaded by this call; "downloaded_sources"
    lists what is on disk and "data_note" says how the user can fetch newer
    prices. Use this whenever a question needs the portfolio's numbers
    rather than policy interpretation. When reporting, state data_source and
    as_of, and if as_of is not the latest completed session, tell the user
    they can refresh from Kite or IBKR or proceed with the latest data
    available.
    """
    return get_analytics(source)


@mcp.tool()
def get_risk_policy_sections(query: str, top_k: int = 2, include_core: bool = False) -> dict:
    """Retrieve the risk policy sections most relevant to a natural-language
    query, e.g. position concentration limits, volatility thresholds, VaR
    limits, or drawdown escalation rules. Use this whenever a question needs
    the firm's policy limits, not the portfolio's numbers.

    Set include_core=True for any question about the portfolio's overall
    risk or limit compliance: it always adds the core limit and escalation
    clauses (RP13, RP15, RP17, RP19, RP25), which a search can miss.
    """
    return {"query": query, "include_core": include_core,
            "results": retrieve(query, top_k=top_k, include_core=include_core)}


if __name__ == "__main__":
    mcp.run()
