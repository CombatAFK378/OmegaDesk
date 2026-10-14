"""Phase 1 seed (§17): reset graph → schema → baseline world + the old closed
case linked to Device D1 (the Track-2 memory lineage the demo leans on).

Deterministic: fixed ids + fixed timestamps → identical counts every run.
Run:  .venv/bin/python -m seed.seed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_graph  # noqa: E402
from seed.schema import EDGE_TYPES, NODE_LABELS, create_schema  # noqa: E402


def create_regulations(g):
    g.query(
        """CREATE (:Regulation {id:'R-STRUCT', section:'§5',
             title:'Structuring below reporting threshold',
             clause:'Multiple sub-threshold inflows converging on one account within a short window indicate structuring. A freeze requires a documented evidence chain.'})
           CREATE (:Regulation {id:'R-VELOCITY', section:'§7',
             title:'Unusual velocity and rapid pass-through',
             clause:'Accounts receiving and forwarding funds within minutes show velocity anomalies; verdict confidence requires a traced money path.'})
           CREATE (:Regulation {id:'R-DEVICE-RING', section:'§9',
             title:'Shared-device rings and identity layering',
             clause:'Accounts sharing a device fingerprint or KYC identity elements are a coordination signal. Check prior cases on the same fingerprint before a verdict.'})"""
    )


def create_analysts(g):
    g.query(
        """CREATE (:Analyst {id:'AN-PRIYA', name:'Priya Nair', team:'AML',
             on_call_today:true, skills:['graph investigations','SAR drafting']})
           CREATE (:Analyst {id:'AN-DEV', name:'Dev Mehta', team:'risk',
             on_call_today:false, skills:['velocity monitoring']})"""
    )


def create_employer(g):
    g.query(
        """CREATE (:Employer {id:'E-MERIDIAN', name:'Meridian Logistics Pvt Ltd',
             business_kyc:true, cadence:'monthly'})"""
    )  # PAID_BY edges arrive with scenario C (Phase 2), not at seed


def create_baseline_accounts(g):
    """12 boring legit customer accounts (A-001..A-012) + Person-HOLDS-Account."""
    people = [
        ("P-001", "Anil Deshmukh", "A-001", True), ("P-002", "Sneha Kulkarni", "A-002", True),
        ("P-003", "Rahul Iyer", "A-003", True), ("P-004", "Meera Pillai", "A-004", False),
        ("P-005", "Karan Malhotra", "A-005", True), ("P-006", "Divya Menon", "A-006", True),
        ("P-007", "Rohan Joshi", "A-007", True), ("P-008", "Ishita Bose", "A-008", True),
        ("P-009", "Sameer Khan", "A-009", True), ("P-010", "Tara Sharma", "A-010", True),
        ("P-011", "Nikhil Rao", "A-011", True), ("P-012", "Pooja Verma", "A-012", True),
    ]
    for pid, name, aid, kyc in people:
        g.query(
            """CREATE (:Person {id:$pid, name:$name, kyc_status:$kyc})
                   -[:HOLDS {since:'2025-01-15'}]->
               (:Account {id:$aid, opened_at:'2025-01-15', type:'customer', status:'active'})""",
            {"pid": pid, "name": name, "kyc": kyc, "aid": aid},
        )
    # four legit transfers — background normality, nothing interesting
    for src, dst, amount, at in [
        ("A-002", "A-001", 22000, "2025-03-02T10:12"),
        ("A-003", "A-004", 18000, "2025-03-03T19:40"),
        ("A-005", "A-002", 31000, "2025-03-04T08:05"),
        ("A-008", "A-010", 9500, "2025-03-05T16:22"),
    ]:
        g.query(
            """MATCH (s:Account {id:$src}), (t:Account {id:$dst})
               CREATE (s)-[:SENT {amount:$amount, timestamp:$at}]->(t)""",
            {"src": src, "dst": dst, "amount": amount, "at": at},
        )


def create_old_case_world(g):
    """The closed case on Device D1 — what `prior_cases(D1)` must return later.

    April 2025: two mule accounts shared device D1, dripped sub-threshold
    inflows into A-R1 overnight, got caught, A-R1 frozen, case closed.
    NOTE: CREATE always makes a NEW node (FalkorDB has no uniqueness
    constraints) — nodes are created once here, then bound with MATCH before
    every edge, never re-CREATEd.
    """
    g.query(
        """CREATE (:Person {id:'P-R1', name:'Raman Shetty', kyc_status:false})
               -[:HOLDS {since:'2025-03-20'}]->
           (:Account {id:'A-R1', opened_at:'2025-03-20', type:'customer', status:'frozen'})
           CREATE (:Person {id:'P-R2', name:'Vikram Rao', kyc_status:false})
               -[:HOLDS {since:'2025-03-21'}]->
           (:Account {id:'A-R2', opened_at:'2025-03-21', type:'customer', status:'frozen'})
           CREATE (:Device {id:'D1', fingerprint:'fp-91d3e7a2c4'})"""
    )
    g.query(
        """MATCH (a1:Account {id:'A-R1'}), (a2:Account {id:'A-R2'}), (d:Device {id:'D1'})
           CREATE (a1)-[:USED_DEVICE {at:'2025-04-16T22:41'}]->(d)
           CREATE (a2)-[:USED_DEVICE {at:'2025-04-16T22:47'}]->(d)
           CREATE (a1)-[:SAME_IDENTITY {reason:'shared nominee and email at KYC',
             discovered:'kyc_review'}]->(a2)"""
    )
    # sub-threshold drip into A-R1 from A-R2 (the old funnel)
    for amount, at in [(47500, "2025-04-16T21:14"), (49200, "2025-04-16T22:03")]:
        g.query(
            """MATCH (s:Account {id:'A-R2'}), (t:Account {id:'A-R1'})
               CREATE (s)-[:SENT {amount:$amount, timestamp:$at}]->(t)""",
            {"amount": amount, "at": at},
        )
    # alert → case → actions/policy/analyst: the full lineage shape
    g.query(
        """MATCH (a1:Account {id:'A-R1'}), (d:Device {id:'D1'}),
               (reg:Regulation {id:'R-STRUCT'}), (an:Analyst {id:'AN-PRIYA'})
           CREATE (al:Alert {id:'AL-2025-0417', type:'fan_in',
             window:'2025-04-16T21:00/23:00', status:'closed', created_at:'2025-04-16T23:05'})
           CREATE (a1)-[:TRIGGERED]->(al)
           CREATE (c:Case {id:'C-2025-0417', verdict:'fraud — device ring layering',
             confidence:0.91, status:'closed', outcome:'A-R1 frozen, SAR filed',
             created_at:'2025-04-17T09:30', closed_at:'2025-04-17T14:10'})
           CREATE (c)-[:INVESTIGATED]->(al)
           CREATE (c)-[:EVIDENCE {finding:'sub-threshold inflow funnel overnight',
             query_id:'q-fan-in', snapshot:'2 senders, total 96700'}]->(a1)
           CREATE (c)-[:EVIDENCE {finding:'same device fingerprint on both accounts',
             query_id:'q-shared-device', snapshot:'2 accounts on fp-91d3e7a2c4'}]->(d)
           CREATE (c)-[:FROZEN_BY {order:'freeze under §5 structuring',
             at:'2025-04-17T13:55'}]->(a1)
           CREATE (c)-[:RESOLVED_AS {decision:'freeze', decided_by:'Priya Nair',
             at:'2025-04-17T14:10'}]->(a1)
           CREATE (c)-[:CITED_BY]->(reg)
           CREATE (c)-[:ASSIGNED_TO]->(an)"""
    )


def graph_counts(g):
    nodes = {}
    for label in NODE_LABELS:
        nodes[label] = g.query(f"MATCH (n:{label}) RETURN count(n)").result_set[0][0]
    edges = {}
    for et in EDGE_TYPES:
        edges[et] = g.query(f"MATCH ()-[r:{et}]->() RETURN count(r)").result_set[0][0]
    return nodes, edges


def seed_graph(g=None):
    """Full reset + rebuild. Returns (node_counts, edge_counts) — asserted, not eyeballed."""
    g = g or get_graph()
    create_schema(g)  # includes data wipe
    create_regulations(g)
    create_analysts(g)
    create_employer(g)
    create_baseline_accounts(g)
    create_old_case_world(g)
    return graph_counts(g)


if __name__ == "__main__":
    nodes, edges = seed_graph()
    print("nodes:", {k: v for k, v in nodes.items() if v}, "total:", sum(nodes.values()))
    print("edges:", {k: v for k, v in edges.items() if v}, "total:", sum(edges.values()))
    print("seeded graph 'desk' from clean state")