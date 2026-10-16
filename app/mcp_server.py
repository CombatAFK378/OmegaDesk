"""C3 — the OmegaDesk MCP server (§16 C3): the desk's tools, exposed over the
Model Context Protocol so ANY MCP client (e.g. Claude Desktop) can run a full
investigation — the same authority + journaling path as the in-house Investigator.

Run: .venv/bin/python -m app.mcp_server     (stdio transport)
Client wiring for Claude Desktop (docs/claude_desktop_config.json):
{"mcpServers": {"omegadesk": {"command": "<abs path to .venv/bin/python>",
                              "args": ["-m", "app.mcp_server"],
                              "cwd": "<repo root>"}}}
"""
from mcp.server.fastmcp import FastMCP

from .coordinator import handle_alert
from .tools import run_tool

mcp = FastMCP("omegadesk")


@mcp.tool()
def investigate_alert(alert_id: str) -> str:
    """Open a case for an alert and run the FULL deterministic pipeline:
    signals → investigator (the only LLM) → policy → Decision/FreezeOrder,
    including proof-of-absence when appropriate. Returns the decision summary."""
    import json
    return json.dumps(handle_alert(alert_id), default=str)[:4000]


@mcp.tool()
def get_case(case_id: str) -> str:
    """Full case detail read-only: scope, signals, decisions, citations,
    evidence chain, token spend."""
    import json
    from .api_cases import case_detail
    return json.dumps(case_detail(case_id), default=str)[:5000]


@mcp.tool()
def read_case_context(case_id: str) -> str:
    """Everything known about the case: scope, holder KYC, computed signals,
    triggering alert, recent transactions, existing decisions."""
    import json
    return json.dumps(run_tool("get_case_context", "investigator", case_id=case_id),
                      default=str)[:3000]


@mcp.tool()
def past_similar_cases(case_id: str, limit: int = 3) -> str:
    """PRECEDENT LOOKUP: past decisions on cases sharing signals, ranked
    (corrections weigh more); overruled decisions are never returned."""
    import json
    return json.dumps(run_tool("find_precedents", "investigator", case_id=case_id,
                               limit=limit), default=str)[:3000]


@mcp.tool()
def follow_the_money(src: str, dst: str, max_hops: int = 4) -> str:
    """Money-route walker: SENT→Transaction→TO chains between two accounts."""
    import json
    return json.dumps(run_tool("trace_money_path", "investigator", src=src, dst=dst,
                               max_hops=max_hops), default=str)[:3000]


@mcp.tool()
def shared_devices_and_counterparties(account_ids: list[str]) -> str:
    """Overlap among suspect accounts: shared devices, identity links,
    shared counterparties/merchants."""
    import json
    return json.dumps(run_tool("find_shared_entities", "investigator",
                               account_ids=account_ids), default=str)[:3000]


@mcp.tool()
def prove_absence_of_fraud(case_id: str) -> str:
    """The negative checklist (§16 C3): shared devices with frozen accounts,
    identity links, payments to frozen accounts, payer structuring, velocity,
    unverified payers. ALL passing = a replayable receipt proving the shape benign."""
    import json
    return json.dumps(run_tool("prove_absence", "investigator", case_id=case_id),
                      default=str)[:3000]


@mcp.tool()
def money_hub(case_id: str, k: int = 1) -> str:
    """Betweenness centrality around the case's money paths: the funnel's heart."""
    import json
    return json.dumps(run_tool("hub_centrality", "investigator", case_id=case_id, k=k),
                      default=str)[:2000]


if __name__ == "__main__":
    mcp.run()