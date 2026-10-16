"""C3 exit tests (v2.1 §16): "an MCP client runs a full investigation;
C is cleared with a proof-of-absence receipt."

Covers:
  1. proof-of-absence: a clean payroll-merchant case → all-absent RECEIPT (+ as_of + digest)
  2. the guard rails: the DARK merchant + the E-trap must NOT get receipts
  3. the full pipeline: investigate C with the LLM → auto-CLEAR + receipt on the decision
     + case closed (the honest-clearance beat — no human needed)
  4. routing: device-rings → AN-PRIYA, merchant shapes → AN-DEV (deterministic + edge written)
  5. hub_centrality: the funnel's heart found in the neighborhood (LLM-free)
  6. an MCP CLIENT runs the full investigation list_tools → investigate via MCP (LLM)

LLM spend: ~2 investigations (~$0.01 on the ollama key).
Run: .venv/bin/python scripts/c3_exit_test.py
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def main():
    from seed.seed import seed_graph
    from sim.generator import inject_scenario_c
    from sim.injectors_c1 import (inject_scenario_c_prime, inject_scenario_d,
                                  inject_scenario_e)
    from app.monitor import scan_once
    from app.coordinator import open_case_for_alert, open_case_direct
    from app.benchmark import _latest_alert_for
    from app.signals import extract_signals
    from app.tools import run_tool
    from app.routing import route_case
    from app.graph import get_graph
    from app.config import LLM_API_KEY
    from app.investigator import _client

    print(f"seed: {seed_graph()}")
    g = get_graph()

    # ---- a fresh merchant world: C + C′ + D + E, all scanned ----
    # ---- world 1: the C + C′ merchant world (receipt + hub + routing + LLM clear) ----
    inject_scenario_c(g)
    inject_scenario_c_prime(g)
    scan_once(g)

    def make_case(target):
        meta = open_case_for_alert(_latest_alert_for(g, target), g)
        meta["target"] = target
        extract_signals(meta["case_id"], g, target=target)
        return meta

    c_case = make_case("A-MER-PAY")

    # ---- 1) the receipt: C's merchant is clean payroll → ALL-ABSENT ----
    rec_c = run_tool("prove_absence", "investigator", case_id=c_case["case_id"])
    check("C: proof-of-absence receipt issues",
          rec_c["receipt"] is True and rec_c["digest"] and rec_c["as_of"],
          f"got {rec_c}")
    check("C: every check reported in plain words + not dangerous",
          all(not chk["dangerous"] for chk in rec_c["checks"]) and len(rec_c["checks"]) >= 6)

    # ---- 3) the full pipeline WITH the LLM: C auto-clears with its receipt ----
    if LLM_API_KEY:
        from app.coordinator import handle_alert
        inv_res = handle_alert(_latest_alert_for(g, "A-MER-PAY"), ablated=False,
                               client=_client(), g=g)
        check("C investigated → CLEARED BY THE DESK (receipt-backed)",
              inv_res["action"] == "clear" and inv_res.get("absence_receipt"),
              f"got {inv_res['action']} receipt={bool(inv_res.get('absence_receipt'))}")
        check("clearance closed the case + receipt stored on the decision",
              inv_res.get("assigned_to") is not None)
        row = g.query(
            f"""MATCH (d:Decision {{id:'{inv_res['dec_id']}'}})-[:FOR_CASE]->(c:Case)
                RETURN d.receipt_digest, c.status""").result_set
        check("decision carries the receipt digest; case status = closed",
              row and row[0][0] is not None and row[0][1] == "closed", f"got {row}")
    else:
        print("SKIP the LLM clear-beat (no key)")

    # ---- 4) routing, deterministic (real cases exist) ----
    open_case_direct("TEST-RING", "A-001", g)
    open_case_direct("TEST-MERCH", "A-002", g)
    r1 = route_case("TEST-RING", [{"code": "SHARED_DEVICE"}], g)
    r2 = route_case("TEST-MERCH", [{"code": "BUSINESS_KYC"}], g)
    check("routing: device-ring → AN-PRIYA", r1["analyst"] == "AN-PRIYA", f"got {r1}")
    check("routing: merchant → AN-DEV", r2["analyst"] == "AN-DEV", f"got {r2}")
    edge = g.query("MATCH (c:Case {id:'TEST-RING'})-[:ASSIGNED_TO]->(an) RETURN an.id").result_set
    check("routing: ASSIGNED_TO edge written", edge == [["AN-PRIYA"]], f"got {edge}")

    # ---- 5) hub centrality (LLM-free) ----
    hub = run_tool("hub_centrality", "investigator", case_id=c_case["case_id"])
    check("hub: found the funnel's heart on the money graph",
          hub["found"] is True and hub["top5"] and hub["betweenness"] >= 0
          and hub["plain"], f"got {hub.get('error') or hub['hub']}")

    # ---- 6) an MCP CLIENT runs the full investigation (same live world) ----
    if LLM_API_KEY:
        async def mcp_probe():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            params = StdioServerParameters(
                command=str(ROOT / ".venv" / "bin" / "python"),
                args=["-m", "app.mcp_server"], cwd=str(ROOT))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = sorted(t.name for t in tools.tools)
                    res = await session.call_tool(
                        "investigate_alert",
                        {"alert_id": _latest_alert_for(g, "A-MER-PAY")})
                    payload = json.loads(res.content[0].text) if res.content else {}
                    return names, payload
        names, payload = asyncio.run(mcp_probe())
        check("MCP client: 8 desk tools visible", len(names) >= 8, f"got {names}")
        check("MCP client: a FULL investigation ran end-to-end",
              payload.get("action") in ("clear", "escalate", "monitor", "freeze")
              and payload.get("case_id"), f"got {payload.get('action')}")

    # ---- 7) the guard rails, each in its own world: D and E get NO receipt ----
    seed_graph()
    inject_scenario_d(g)
    scan_once(g)
    d_case = make_case("A-DARK-MER")
    rec_d = run_tool("prove_absence", "investigator", case_id=d_case["case_id"])
    check("D (no KYC): no proof-of-absence receipt", rec_d["receipt"] is False,
          f"got {[c['id'] + ':' + str(c['dangerous']) for c in rec_d['checks'] if c['dangerous']]}")

    seed_graph()
    inject_scenario_e(g)
    open_case_direct("E-TRAP-C3", "A-E1", g)
    extract_signals("E-TRAP-C3", g, target="A-E1")
    rec_e = run_tool("prove_absence", "investigator", case_id="E-TRAP-C3")
    check("E (pass-through chain): no receipt",
          rec_e["receipt"] is False, f"got {rec_e['plain']}")

    print("---")
    if FAILURES:
        print(f"C3 EXIT TEST: {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("C3 EXIT TEST: ALL GREEN")


if __name__ == "__main__":
    main()