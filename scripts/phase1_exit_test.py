"""Phase 1 exit tests — v2 model (v2.1 §16 R1):

  1. Seed → EXACT expected node/edge counts (asserted, not eyeballed)
  2. The D1 case is a real Decision + FreezeOrder precedent (Cypher-verified)
  3. History integrity: 27 decisions, 3 overrides, the E-trap pair exists
  4. Reset + rerun → identical counts (idempotent)

Run: .venv/bin/python scripts/phase1_exit_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_graph  # noqa: E402
from seed.schema import graph_counts  # noqa: E402
from seed.seed import seed_graph  # noqa: E402

EXPECTED_NODES = {
    "Person": 14, "Account": 15, "Device": 1, "Merchant": 1, "Transaction": 6,
    "Alert": 25, "Case": 25, "Signal": 9, "Decision": 28, "FreezeOrder": 9,
    "Analyst": 2, "Regulation": 4,                                   # → 139
}
EXPECTED_EDGES = {
    "SENT": 6, "TO": 6, "USED_DEVICE": 2, "SAME_IDENTITY": 1, "OWNS": 14,
    "OPERATED_BY": 1, "TRIGGERED_BY": 2, "FOR_ALERT": 25, "ABOUT": 50,
    "EXHIBITS": 51, "EVIDENCE": 26, "FOR_CASE": 28, "CITES": 8, "OVERRIDES": 3,
    "APPLIED_POLICY": 28, "MADE_BY": 28, "FREEZES": 9, "ISSUED_BY": 9,
    "ASSIGNED_TO": 25,                                               # → 322
}
FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def match_counts(nodes, edges):
    check("node counts exact", nodes == EXPECTED_NODES, f"got {nodes}")
    check("edge counts exact", edges == EXPECTED_EDGES, f"got {edges}")
    check("totals 139 nodes / 322 edges",
          sum(nodes.values()) == 139 and sum(edges.values()) == 322,
          f"got {sum(nodes.values())}/{sum(edges.values())}")


def lineage(g):
    path = g.query(
        "MATCH (d:Device {id:'D1'})<-[:USED_DEVICE]-(a:Account)<-[:ABOUT]-(c:Case) "
        "RETURN count(DISTINCT c)").result_set[0][0]
    check("D1→account→case path exists (ABOUT scope)", path == 1, f"got {path}")

    fo = g.query(
        "MATCH (fo:FreezeOrder)-[:FREEZES]->(:Account {id:'A-R1'}), "
        "(fo)-[:ISSUED_BY]->(d:Decision) RETURN d.confidence").result_set
    check("A-R1 frozen by a FreezeOrder issued by the 0.91 decision", fo == [[0.91]], f"got {fo}")

    cited = g.query(
        "MATCH (:Decision {id:'D-2025-0417'})-[:APPLIED_POLICY]->(r:Regulation) RETURN r.id"
    ).result_set
    check("decision cites the §5 structuring clause", cited == [["R-STRUCT"]], f"got {cited}")

    overruled = g.query(
        "MATCH (d:Decision)<-[:OVERRIDES]-() RETURN count(d)").result_set[0][0]
    check("history has exactly 3 override-corrected decisions", overruled == 3, f"got {overruled}")

    trap = g.query(
        "MATCH (ov:Decision)-[:OVERRIDES]->(old:Decision {id:'HD-019'}) RETURN ov.id"
    ).result_set
    check("E-trap ready: HD-019 was overruled by HOV-002", trap == [["HOV-002"]], f"got {trap}")

    merchant = g.query(
        "MATCH (a:Account {id:'A-MER-PAY'})-[:OPERATED_BY]->(m:Merchant) "
        "RETURN m.business_kyc").result_set
    check("merchant account ready for scenario C (business KYC)", merchant == [[True]],
          f"got {merchant}")


def main():
    seed_graph()
    g = get_graph()
    nodes1, edges1 = graph_counts(g)
    print("--- seed run 1 ---")
    match_counts(nodes1, edges1)
    lineage(g)

    nodes2, edges2 = seed_graph()
    print("--- seed run 2 (reset + rerun, must be identical) ---")
    match_counts(nodes2, edges2)
    check("idempotent: second run identical to first", (nodes1, edges1) == (nodes2, edges2))

    print("---")
    if FAILURES:
        print(f"PHASE 1 EXIT TEST (v2): {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("PHASE 1 EXIT TEST (v2): ALL GREEN")


if __name__ == "__main__":
    main()