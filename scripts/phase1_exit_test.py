"""Phase 1 exit tests (§17):

  1. Run seed → EXACT expected node/edge counts (asserted, not eyeballed)
  2. Old case visibly linked to Device D1 (Cypher-verified lineage)
  3. Reset + rerun seed → identical counts (idempotent)

Run: .venv/bin/python scripts/phase1_exit_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_graph  # noqa: E402
from seed.seed import graph_counts, seed_graph  # noqa: E402

EXPECTED_NODES = {
    "Person": 14, "Account": 14, "Device": 1, "Employer": 1,
    "Regulation": 3, "Analyst": 2, "Case": 1, "Alert": 1,          # → 37
}
EXPECTED_EDGES = {
    "SENT": 6, "USED_DEVICE": 2, "SAME_IDENTITY": 1, "TRIGGERED": 1,
    "INVESTIGATED": 1, "EVIDENCE": 2, "RESOLVED_AS": 1, "FROZEN_BY": 1,
    "CITED_BY": 1, "ASSIGNED_TO": 1,
    "PAID_BY": 0,  # arrives with scenario C (Phase 2) — baseline asserts zero
    "HOLDS": 14,  # Person→Account (§4 gap, flagged)               # → 31
}
FAILURES = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def match_counts(nodes, edges):
    check("node counts exact", nodes == EXPECTED_NODES, f"got {nodes}")
    check("edge counts exact", edges == EXPECTED_EDGES, f"got {edges}")
    check(
        "totals 37 nodes / 31 edges",
        sum(nodes.values()) == 37 and sum(edges.values()) == 31,
        f"got {sum(nodes.values())}/{sum(edges.values())}",
    )


def lineage():
    g = get_graph()
    direct = g.query(
        "MATCH (c:Case)-[:EVIDENCE]->(d:Device {id:'D1'}) RETURN c.id"
    ).result_set
    check("old case EVIDENCE-linked to D1", direct == [["C-2025-0417"]], f"got {direct}")

    via_account = g.query(
        "MATCH (d:Device {id:'D1'})<-[:USED_DEVICE]-(a:Account)<-[:EVIDENCE]-(c:Case) "
        "RETURN count(DISTINCT c)"
    ).result_set[0][0]
    check("D1→account→case path exists", via_account == 1, f"got {via_account}")

    frozen = g.query(
        "MATCH (:Case {id:'C-2025-0417'})-[:FROZEN_BY]->(a:Account) RETURN a.status"
    ).result_set
    check("FROZEN_BY hits a frozen account", frozen == [["frozen"]], f"got {frozen}")

    cited = g.query(
        "MATCH (:Case {id:'C-2025-0417'})-[:CITED_BY]->(r:Regulation) RETURN r.id"
    ).result_set
    check("case cites §5 structuring clause", cited == [["R-STRUCT"]], f"got {cited}")


def main():
    nodes1, edges1 = seed_graph()
    print("--- seed run 1 ---")
    match_counts(nodes1, edges1)
    lineage()

    nodes2, edges2 = seed_graph()
    print("--- seed run 2 (reset + rerun, must be identical) ---")
    match_counts(nodes2, edges2)
    check("idempotent: second run identical to first", (nodes1, edges1) == (nodes2, edges2))

    print("---")
    if FAILURES:
        print(f"PHASE 1 EXIT TEST: {len(FAILURES)} failure(s): {FAILURES}")
        sys.exit(1)
    print("PHASE 1 EXIT TEST: ALL GREEN")


if __name__ == "__main__":
    main()