"""Phase 4 exit tests — v2 tool layer (v2.1 §16 R4):

  1. Registry = the §9 core-4 + whitelist; no write tools (policy engine is code)
  2. find_precedents works on a real case: signal overlap + proximity ranking,
     and the OVERRULED precedent is never returned (E-trap gate)
  3. trace_money_path v2 (Transaction chains) + whitelist still rejects rogue Cypher
  4. Ablation switch now governs find_precedents (the with/without benchmark hook)
  5. Policy engine (§10): decision table + override safety rule as code

Run: .venv/bin/python scripts/phase4_exit_test.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.journal import JOURNAL_PATH  # noqa: E402
from app.graph import get_graph  # noqa: E402
from app.policy import decide_action, override_action  # noqa: E402
from app.tools import TOOL_REGISTRY, run_tool  # noqa: E402
from app.tools.registry import set_memory_ablation  # noqa: E402
from seed.seed import seed_graph  # noqa: E402
from sim.generator import inject_scenario_a  # noqa: E402

FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def raises(exc_type, fn, **kw):
    try:
        fn(**kw)
        return False, None
    except exc_type as e:
        return True, e


def make_test_case(g, cid, about_ids, signals, created):
    g.query("CREATE (c:Case {id:$cid, status:'open', created_at:$created})",
            {"cid": cid, "created": created})
    for aid in about_ids:
        g.query("MATCH (c:Case {id:$cid}), (a:Account {id:$aid}) "
                "CREATE (c)-[:ABOUT {ts:$created}]->(a)",
                {"cid": cid, "aid": aid, "created": created})
    for sc in signals:
        g.query("MATCH (c:Case {id:$cid}), (s:Signal {code:$sc}) "
                "CREATE (c)-[:EXHIBITS {value:1, as_of:$created}]->(s)",
                {"cid": cid, "sc": sc, "created": created})


def main():
    seed_graph()
    inject_scenario_a()  # ring on D1 + funnel to A-EXIT
    lines_before = len(JOURNAL_PATH.read_text(encoding="utf-8").splitlines()) \
        if JOURNAL_PATH.exists() else 0

    g = get_graph()
    inv = "investigator"

    # test case C1 rides the ring (A-M1 shares D1); C2 rides H-C019's exact
    # signals (§11: bundle B = PASS_THROUGH + NEW_ACCOUNT) + its home account
    make_test_case(g, "TEST-C1", ["A-M1", "A-EXIT"], ["SHARED_DEVICE", "FAN_IN"],
                   "2026-02-06T04:00")
    make_test_case(g, "TEST-C2", ["A-002"], ["PASS_THROUGH", "NEW_ACCOUNT"],
                   "2026-02-06T04:10")

    print("--- registry (v2 §9) ---")
    names = sorted(TOOL_REGISTRY)
    check("registry = core-4 + whitelist (all read)",
          names == ["find_precedents", "find_shared_entities", "get_case_context",
                    "run_cypher_readonly", "trace_money_path"]
          and all(t.kind == "read" for t in TOOL_REGISTRY.values()), f"got {names}")
    check("write tools are gone (policy engine is code — §5/§10)",
          "freeze_account" not in TOOL_REGISTRY and not any(
              t.kind == "write" for t in TOOL_REGISTRY.values()))

    print("--- find_precedents (§8) ---")
    p1 = run_tool("find_precedents", inv, case_id="TEST-C1")
    check("C1: the 2025 D1 Decision ranks FIRST (2 shared signals + true proximity)",
          p1["precedents"] and p1["precedents"][0]["decision_id"] == "D-2025-0417"
          and p1["precedents"][0]["proximity"] is True, f"got {p1['precedents'][:1]}")
    check("C1: top-3 shape (≤3, each with shared_signals listed)",
          1 <= len(p1["precedents"]) <= 3
          and all(p["shared_signals"] for p in p1["precedents"]), f"got {len(p1['precedents'])}")

    p2 = run_tool("find_precedents", inv, case_id="TEST-C2")
    ids2 = [p["decision_id"] for p in p2["precedents"]]
    check("E-trap: the OVERRULED HD-019 is NEVER cited (R4 gate)",
          "HD-019" not in ids2, f"got {ids2}")
    check("E-trap: the correcting HOV-002 IS returned instead",
          "HOV-002" in ids2, f"got {ids2}")

    print("--- get_case_context ---")
    ctx = run_tool("get_case_context", inv, case_id="TEST-C1")
    check("context: scope + signals + no alert + no decisions yet",
          ctx["found"] and {"A-M1", "A-EXIT"} <= {a["id"] for a in ctx["accounts"]}
          and {s["code"] for s in ctx["signals"]} == {"SHARED_DEVICE", "FAN_IN"}
          and ctx["alert"] is None and ctx["decisions"] == [], f"got {ctx}")

    print("--- trace_money_path v2 ---")
    trace = run_tool("trace_money_path", inv, src="A-F1", dst="A-EXIT", max_hops=3)
    got = sorted(p["path"] for p in trace["paths"])
    check("trace: 2-hop chains through Transaction nodes (F1→M1→EXIT, F1→M2→EXIT)",
          trace["count"] == 2
          and got == [["A-F1", "A-M1", "A-EXIT"], ["A-F1", "A-M2", "A-EXIT"]], f"got {trace}")
    amounts = sorted(l["amount"] for l in trace["paths"][0]["legs"])
    check("trace: per-leg amounts from Transaction nodes",
          amounts in ([48700.0, 48900.0], [49000.0, 49250.0]), f"got {amounts}")

    sh = run_tool("find_shared_entities", inv, account_ids=["A-M1", "A-M2", "A-M3"])
    check("shared entities: D1 shared across suspects",
          any(s["device"] == "D1" and len(s["used_by"]) >= 3 for s in sh["shared_devices"]),
          f"got {sh}")

    print("--- whitelist (kept per R4 gate) ---")
    allowed = run_tool("run_cypher_readonly", inv,
                       pattern_cypher="MATCH (a:Account {id:$id}) RETURN a.id LIMIT 5",
                       params={"id": "A-EXIT"})
    check("whitelist accepts approved param lookup", allowed["rows"] == [["A-EXIT"]],
          f"got {allowed}")
    chain = run_tool("run_cypher_readonly", inv,
                     pattern_cypher="MATCH (a:Account {id:'A-F1'})-[:SENT]->(t:Transaction)"
                                    "-[:TO]->(m:Account) RETURN a.id, t.id, m.id LIMIT 5")
    check("whitelist accepts the approved v2 chain shape", len(chain["rows"]) == 2, f"got {chain}")
    ok_kw, _ = raises(PermissionError, run_tool, name="run_cypher_readonly", actor_role=inv,
                      pattern_cypher="MATCH (n) DETACH DELETE n")
    check("whitelist rejects DETACH DELETE", ok_kw)
    ok_shape, _ = raises(PermissionError, run_tool, name="run_cypher_readonly", actor_role=inv,
                         pattern_cypher="MATCH (a:Account)-[r:SENT]->(t:Account) RETURN a.id")
    check("whitelist rejects the v1 legacy shape (edge-to-edge)", ok_shape)

    print("--- policy engine (§10, code not model) ---")
    check("policy: ≥0.85 + no mitigating → freeze", decide_action(0.9, False, True) == "freeze")
    check("policy: ≥0.85 + mitigating precedent → escalate",
          decide_action(0.9, True, True) == "escalate")
    check("policy: 0.60–0.85 → escalate", decide_action(0.70) == "escalate")
    check("policy: <0.60 → monitor", decide_action(0.40) == "monitor")
    check("policy: absence + mitigating + no aggravating → clear",
          decide_action(0.50, True, False, True) == "clear")
    check("override safety: override can only push toward escalate (§10)",
          override_action("freeze", "analyst says too thin") == "escalate")
    ok_reason, _ = raises(ValueError, override_action, base_action="freeze", reason="")
    check("override safety: no reason → not recorded", ok_reason)

    print("--- ablation → governs find_precedents (§12 with/without hook) ---")
    set_memory_ablation(True)
    stripped = run_tool("find_precedents", inv, case_id="TEST-C2")
    check("ablation ON: precedents stripped",
          stripped == {"ablated": True, "precedents": [], "case_id": "TEST-C2"}, f"got {stripped}")
    set_memory_ablation(False)
    restored = run_tool("find_precedents", inv, case_id="TEST-C2")
    check("ablation OFF: precedents back (HOV-002 present)",
          not restored.get("ablated") and "HOV-002" in
          [p["decision_id"] for p in restored["precedents"]], f"got {restored}")

    ok_role, _ = raises(PermissionError, run_tool, name="get_case_context",
                        actor_role="executor", case_id="TEST-C1")
    check("authority: executor role cannot call read tools", ok_role)

    print("--- journal evidence ---")
    entries = [json.loads(l) for l in
               JOURNAL_PATH.read_text(encoding="utf-8").splitlines()[lines_before:]]
    calls = [e for e in entries if e["action"] == "tool_call"]
    rejects = [e for e in entries if e["action"] == "authority_rejected"]
    ablated = [e for e in entries if e["action"] == "memory_ablated"]
    check("journal: read tool calls journaled with roles (ablated call counts too)",
          len(calls) + len(ablated) >= 9,
          f"got {len(calls)} calls / {len(ablated)} ablated / {len(rejects)} rejections")
    check("journal: executor's read attempt recorded as authority rejection",
          {e["role"] for e in rejects} == {"executor"}, f"got {rejects}")
    check("journal: ablation journaled on find_precedents",
          len(ablated) == 1 and ablated[0]["tool"] == "find_precedents", f"got {ablated}")

    print("---")
    if FAILURES:
        print(f"PHASE 4 EXIT TEST (v2): {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("PHASE 4 EXIT TEST (v2): ALL GREEN")


if __name__ == "__main__":
    main()