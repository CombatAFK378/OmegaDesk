"""Seed — architecture v2.1 §6/§11: reset → v2 world → the desk's history.

Reworked (R1): transfers are Transaction nodes; Account has no status (freezes
are FreezeOrder events); the D1 case now carries a real `Decision` (+FreezeOrder)
so scenario A has a citable precedent; plus 24 historical cases = 27 decisions
(3 analyst corrections, one of which overrules an earlier decision — the E-trap).

Deterministic: fixed ids, timestamps, loops → identical counts on every run.
Run: .venv/bin/python -m seed.seed
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.graph import get_graph  # noqa: E402
from seed.schema import create_schema, graph_counts  # noqa: E402

# ---- history composition (§11: 20–40 decisions; 3 corrections; 1 overruled) ----
H_CASES = 24
FREEZE_SET = {3, 5, 8, 11, 14, 19, 20, 23}   # fraud/freeze → 8 FreezeOrders
ESCALATE_SET = {2, 6, 9, 12, 16, 21, 24}     # unclear/escalate
# the rest (9): legit/monitor
OVERRIDES = {  # case index → (analyst, action, reason)
    6:  ("AN-PRIYA", "escalate", "same sender repeated twice this month — watch, don't clear"),
    19: ("AN-PRIYA", "escalate", "shared-device signal too thin alone — need money-shape proof"),
    23: ("AN-DEV",   "clear",    "KYC-verified merchant on registered cadence — business activity"),
}
BUNDLES = [  # rotating 2-signal bundles (index = i % 6)
    ("FAN_IN", "SUB_THRESHOLD"),
    ("PASS_THROUGH", "NEW_ACCOUNT"),
    ("SHARED_DEVICE", "FAN_IN"),
    ("SUB_THRESHOLD", "SHARED_IDENTITY"),
    ("BUSINESS_KYC", "REGULAR_CADENCE"),
    ("RING_MEMBER", "PASS_THROUGH"),
]
CITES = [4, 8, 12, 16, 24, 10, 18, 22]       # HD-i cites HD-(i-1); never cites HD-019

REGULATIONS = [
    ("R-STRUCT", "§5", "Structuring below reporting threshold",
     "Multiple sub-threshold inflows converging on one account within a short window indicate structuring. A freeze requires a documented evidence chain."),
    ("R-VELOCITY", "§7", "Unusual velocity and rapid pass-through",
     "Accounts receiving and forwarding funds within minutes show velocity anomalies; verdict confidence requires a traced money path."),
    ("R-DEVICE-RING", "§9", "Shared-device rings and identity layering",
     "Accounts sharing a device fingerprint or KYC identity elements are a coordination signal. Check precedents on the same fingerprint before a verdict."),
    ("R-MERCH", "§6", "Merchant false-positive clearance",
     "Fan-in into a KYC-verified merchant on its registered cadence is business activity; clear unless aggravating signals accrue."),
]
SIGNALS = [
    ("FAN_IN", "Fan-in burst", "aggravating"),
    ("SUB_THRESHOLD", "Sub-threshold drip", "aggravating"),
    ("PASS_THROUGH", "Rapid pass-through", "aggravating"),
    ("SHARED_DEVICE", "Shared device", "aggravating"),
    ("SHARED_IDENTITY", "Shared KYC identity", "aggravating"),
    ("NEW_ACCOUNT", "Fresh account", "aggravating"),
    ("RING_MEMBER", "Community ring member", "aggravating"),
    ("BUSINESS_KYC", "KYC-verified merchant", "mitigating"),
    ("REGULAR_CADENCE", "Registered cadence", "mitigating"),
]
_REG_BY_SIGNAL = {"FAN_IN": "R-STRUCT", "SUB_THRESHOLD": "R-STRUCT",
                  "PASS_THROUGH": "R-VELOCITY", "SHARED_DEVICE": "R-DEVICE-RING",
                  "SHARED_IDENTITY": "R-DEVICE-RING", "NEW_ACCOUNT": "R-STRUCT",
                  "RING_MEMBER": "R-DEVICE-RING", "BUSINESS_KYC": "R-MERCH",
                  "REGULAR_CADENCE": "R-MERCH"}
_TYPE_BY_SIGNAL = {"FAN_IN": "fan_in", "SUB_THRESHOLD": "sub_threshold",
                   "PASS_THROUGH": "velocity", "SHARED_DEVICE": "fan_in",
                   "SHARED_IDENTITY": "identity", "NEW_ACCOUNT": "velocity",
                   "RING_MEMBER": "fan_in", "BUSINESS_KYC": "fan_in",
                   "REGULAR_CADENCE": "fan_in"}


def _reg_for(i):
    return _REG_BY_SIGNAL[BUNDLES[i % 6][0]]


def _txn(g, tid, amount, ts, src, dst):
    g.query(
        """MATCH (s:Account {id:$src}), (d:Account {id:$dst})
           CREATE (s)-[:SENT {ts:$ts}]
                  ->(:Transaction {id:$tid, amount:$amount, ts:$ts})
                  -[:TO {ts:$ts}]->(d)""",
        {"tid": tid, "amount": amount, "ts": ts, "src": src, "dst": dst},
    )


def _new_person_account(g, pid, pname, kyc, aid, since, acc_type="customer"):
    g.query(
        """CREATE (:Person {id:$pid, name:$pname, kyc_status:$kyc})
               -[:OWNS {ts:$since}]->
           (:Account {id:$aid, opened_at:$since, type:$acc_type})""",
        {"pid": pid, "pname": pname, "kyc": kyc, "aid": aid, "since": since, "acc_type": acc_type},
    )


def create_catalog(g):
    for code, label, polarity in SIGNALS:
        g.query("CREATE (:Signal {code:$code, label:$label, polarity:$polarity})",
                {"code": code, "label": label, "polarity": polarity})
    for rid, section, title, clause in REGULATIONS:
        g.query("CREATE (:Regulation {id:$rid, section:$s, title:$t, clause:$c, fictional:true})",
                {"rid": rid, "s": section, "t": title, "c": clause})
    g.query("""CREATE (:Analyst {id:'AN-PRIYA', name:'Priya Nair', team:'AML',
                 on_call:true, skills:['graph investigations','SAR drafting']})""")
    g.query("""CREATE (:Analyst {id:'AN-DEV', name:'Dev Mehta', team:'risk',
                 on_call:false, skills:['velocity monitoring']})""")


def create_baseline_world(g):
    people = [
        ("P-001", "Anil Deshmukh", "A-001", True), ("P-002", "Sneha Kulkarni", "A-002", True),
        ("P-003", "Rahul Iyer", "A-003", True), ("P-004", "Meera Pillai", "A-004", False),
        ("P-005", "Karan Malhotra", "A-005", True), ("P-006", "Divya Menon", "A-006", True),
        ("P-007", "Rohan Joshi", "A-007", True), ("P-008", "Ishita Bose", "A-008", True),
        ("P-009", "Sameer Khan", "A-009", True), ("P-010", "Tara Sharma", "A-010", True),
        ("P-011", "Nikhil Rao", "A-011", True), ("P-012", "Pooja Verma", "A-012", True),
    ]
    for pid, pname, aid, kyc in people:
        _new_person_account(g, pid, pname, kyc, aid, "2025-01-15")
    for i, (src, dst, amount, ts) in enumerate([
        ("A-002", "A-001", 22000, "2025-03-02T10:12"),
        ("A-003", "A-004", 18000, "2025-03-03T19:40"),
        ("A-005", "A-002", 31000, "2025-03-04T08:05"),
        ("A-008", "A-010", 9500, "2025-03-05T16:22"),
    ], start=1):
        _txn(g, f"TX-B{i:03d}", amount, ts, src, dst)
    g.query("CREATE (:Merchant {id:'M-MERIDIAN', business_kyc:true, registered_cadence:'monthly'})")
    # NOTE: bind the merchant with MATCH — CREATE would duplicate it (no uniqueness constraints)
    g.query("""MATCH (m:Merchant {id:'M-MERIDIAN'})
               CREATE (:Account {id:'A-MER-PAY', opened_at:'2025-01-10', type:'merchant'})
                      -[:OPERATED_BY {ts:'2025-01-10'}]->(m)""")
    g.query("CREATE (:Device {id:'D1', fingerprint:'fp-91d3e7a2c4'})")


def create_old_d1_case(g):
    """April-2025 ring on D1 → Decision + FreezeOrder = scenario A's precedent."""
    _new_person_account(g, "P-R1", "Raman Shetty", False, "A-R1", "2025-03-20")
    _new_person_account(g, "P-R2", "Vikram Rao", False, "A-R2", "2025-03-21")
    g.query("""MATCH (a1:Account {id:'A-R1'}), (a2:Account {id:'A-R2'}), (d:Device {id:'D1'})
               CREATE (a1)-[:USED_DEVICE {ts:'2025-04-16T22:41'}]->(d)
               CREATE (a2)-[:USED_DEVICE {ts:'2025-04-16T22:47'}]->(d)
               CREATE (a1)-[:SAME_IDENTITY {ts:'2025-03-20', reason:'shared nominee and email at KYC'}]->(a2)""")
    _txn(g, "TX-O001", 47500, "2025-04-16T21:14", "A-R2", "A-R1")
    _txn(g, "TX-O002", 49200, "2025-04-16T22:03", "A-R2", "A-R1")
    # NOTE (FalkorDB v6 engine bug): a long chain of CREATE clauses in one query
    # leaves behind a phantom BARE node (verified by bisection). Keep long
    # create-blocks split into short queries — always.
    g.query(
        """MATCH (t1:Transaction {id:'TX-O001'}), (t2:Transaction {id:'TX-O002'})
           CREATE (al:Alert {id:'AL-2025-0417', type:'fan_in', target_id:'A-R1',
                     window_start:'2025-04-16T21:00', window_end:'2025-04-16T23:00',
                     created_at:'2025-04-16T23:05'})
           CREATE (al)-[:TRIGGERED_BY {ts:'2025-04-16T22:03'}]->(t1)
           CREATE (al)-[:TRIGGERED_BY {ts:'2025-04-16T22:03'}]->(t2)"""
    )
    g.query(
        """MATCH (a1:Account {id:'A-R1'}), (a2:Account {id:'A-R2'}), (d:Device {id:'D1'}),
               (al2:Alert {id:'AL-2025-0417'}),
               (reg:Regulation {id:'R-STRUCT'}), (an:Analyst {id:'AN-PRIYA'}),
               (t1:Transaction {id:'TX-O001'}), (sf:Signal {code:'FAN_IN'}),
               (ss:Signal {code:'SUB_THRESHOLD'}), (sd:Signal {code:'SHARED_DEVICE'})
           CREATE (c:Case {id:'C-2025-0417', status:'closed', created_at:'2025-04-17T09:30',
                     closed_at:'2025-04-17T14:10'})
           CREATE (c)-[:FOR_ALERT {ts:'2025-04-17T09:30'}]->(al2)
           CREATE (c)-[:ABOUT {ts:'2025-04-17T09:30'}]->(a1)
           CREATE (c)-[:ABOUT {ts:'2025-04-17T09:30'}]->(a2)
           CREATE (c)-[:EXHIBITS {value:2, as_of:'2025-04-17T09:30'}]->(sf)
           CREATE (c)-[:EXHIBITS {value:2, as_of:'2025-04-17T09:30'}]->(ss)
           CREATE (c)-[:EXHIBITS {value:1, as_of:'2025-04-17T09:30'}]->(sd)
           CREATE (c)-[:EVIDENCE {query_id:'q-shared-device', snapshot:'2 accounts on fp-91d3e7a2c4', as_of:'2025-04-17T09:30'}]->(d)
           CREATE (c)-[:EVIDENCE {query_id:'q-drip-txn', snapshot:'TX-O001 47500; TX-O002 49200', as_of:'2025-04-17T09:30'}]->(t1)
           CREATE (c)-[:ASSIGNED_TO {ts:'2025-04-17T09:35'}]->(an)""",
    )
    g.query(
        """MATCH (a1:Account {id:'A-R1'}), (reg:Regulation {id:'R-STRUCT'}),
               (an:Analyst {id:'AN-PRIYA'}), (c:Case {id:'C-2025-0417'})
           CREATE (dec:Decision {id:'D-2025-0417', ts:'2025-04-17T14:10', verdict:'fraud',
                     action:'freeze', confidence:0.91, decided_by:'analyst',
                     rationale:'Two unverified accounts share device D1 and dripped sub-threshold amounts into A-R1; §5 structuring.', policy_version:'2025-04'})
           CREATE (dec)-[:FOR_CASE {ts:'2025-04-17T14:10'}]->(c)
           CREATE (dec)-[:MADE_BY {ts:'2025-04-17T14:10'}]->(an)
           CREATE (dec)-[:APPLIED_POLICY {ts:'2025-04-17T14:10'}]->(reg)
           CREATE (fo:FreezeOrder {id:'FO-2025-0417', ts:'2025-04-17T13:55'})
           CREATE (fo)-[:FREEZES {ts:'2025-04-17T13:55'}]->(a1)
           CREATE (fo)-[:ISSUED_BY {ts:'2025-04-17T13:55'}]->(dec)"""
    )


def create_history(g):
    """24 historical cases → 27 decisions (3 corrections, one overrules), 8 freezes."""
    for i in range(1, H_CASES + 1):
        cid = f"H-C{i:03d}"
        d1, d2 = f"A-{((i * 2 - 1) % 12) + 1:03d}", f"A-{((i * 2) % 12) + 1:03d}"
        ts = f"2025-06-{1 + (i - 1) // 2:02d}T{10 if i % 2 else 14}:00"
        if i in FREEZE_SET:
            verdict, action, conf = "fraud", "freeze", 0.93
        elif i in ESCALATE_SET:
            verdict, action, conf = "unclear", "escalate", 0.68
        else:
            verdict, action, conf = "legit", "monitor", 0.41
        analyst = "AN-PRIYA" if i % 2 else "AN-DEV"
        sigs = BUNDLES[i % 6]
        alert_type = _TYPE_BY_SIGNAL[sigs[0]]
        g.query(
            f"""MATCH (a1:Account {{id:'{d1}'}}), (a2:Account {{id:'{d2}'}}),
                    (an:Analyst {{id:'{analyst}'}}), (reg:Regulation {{id:'{_reg_for(i)}'}}),
                    (s1:Signal {{code:'{sigs[0]}'}}), (s2:Signal {{code:'{sigs[1]}'}})
                CREATE (al:Alert {{id:'AL-H{i:03d}', type:'{alert_type}', target_id:'{d1}',
                          window_start:'{ts}', window_end:'{ts}', created_at:'{ts}'}})
                CREATE (c:Case {{id:'{cid}', status:'closed', created_at:'{ts}', closed_at:'{ts}'}})
                CREATE (c)-[:FOR_ALERT {{ts:'{ts}'}}]->(al)
                CREATE (c)-[:ABOUT {{ts:'{ts}'}}]->(a1)
                CREATE (c)-[:ABOUT {{ts:'{ts}'}}]->(a2)
                CREATE (c)-[:EXHIBITS {{value:1, as_of:'{ts}'}}]->(s1)
                CREATE (c)-[:EXHIBITS {{value:1, as_of:'{ts}'}}]->(s2)
                CREATE (c)-[:EVIDENCE {{query_id:'q-hist-context',
                          snapshot:'case {cid} context as_of {ts}', as_of:'{ts}'}}]->(a1)
                CREATE (c)-[:ASSIGNED_TO {{ts:'{ts}'}}]->(an)
                CREATE (dec:Decision {{id:'HD-{i:03d}', ts:'{ts}', verdict:'{verdict}',
                          action:'{action}', confidence:{conf}, decided_by:'analyst',
                          rationale:'historical case {cid}', policy_version:'2025-06'}})
                CREATE (dec)-[:FOR_CASE {{ts:'{ts}'}}]->(c)
                CREATE (dec)-[:MADE_BY {{ts:'{ts}'}}]->(an)
                CREATE (dec)-[:APPLIED_POLICY {{ts:'{ts}'}}]->(reg)"""
        )
        if action == "freeze":
            g.query(
                f"""MATCH (a:Account {{id:'{d1}'}}), (dec:Decision {{id:'HD-{i:03d}'}})
                    CREATE (fo:FreezeOrder {{id:'FO-H{i:03d}', ts:'{ts}'}})
                    CREATE (fo)-[:FREEZES {{ts:'{ts}'}}]->(a)
                    CREATE (fo)-[:ISSUED_BY {{ts:'{ts}'}}]->(dec)""")

    for i in CITES:
        cts = f"2025-06-{1 + (i - 1) // 2:02d}T12:00"
        g.query(
            f"""MATCH (a:Decision {{id:'HD-{i:03d}'}}), (b:Decision {{id:'HD-{i - 1:03d}'}})
                CREATE (a)-[:CITES {{applies:true, distinguishing:'', ts:'{cts}'}}]->(b)"""
        )

    for n, (ci, (analyst, action, reason)) in enumerate(sorted(OVERRIDES.items()), start=1):
        ots = f"2025-06-{1 + (ci - 1) // 2:02d}T18:00"
        verdict = {"clear": "legit", "escalate": "unclear"}[action]
        conf = 0.88 if action == "clear" else 0.66
        g.query(
            f"""MATCH (c:Case {{id:'H-C{ci:03d}'}}), (old:Decision {{id:'HD-{ci:03d}'}}),
                    (an:Analyst {{id:'{analyst}'}}), (reg:Regulation {{id:'{_reg_for(ci)}'}})
                CREATE (ov:Decision {{id:'HOV-{n:03d}', ts:'{ots}', verdict:'{verdict}',
                          action:'{action}', confidence:{conf}, decided_by:'analyst',
                          rationale:$reason, policy_version:'2025-06'}})
                CREATE (ov)-[:FOR_CASE {{ts:'{ots}'}}]->(c)
                CREATE (ov)-[:OVERRIDES {{reason:$reason, ts:'{ots}'}}]->(old)
                CREATE (ov)-[:MADE_BY {{ts:'{ots}'}}]->(an)
                CREATE (ov)-[:APPLIED_POLICY {{ts:'{ots}'}}]->(reg)""",
            {"reason": reason},
        )


def seed_graph(g=None):
    """Full reset + v2 rebuild. Returns (node_counts, edge_counts)."""
    g = g or get_graph()
    create_schema(g)  # includes data wipe
    create_catalog(g)
    create_baseline_world(g)
    create_old_d1_case(g)
    create_history(g)
    return graph_counts(g)


if __name__ == "__main__":
    nodes, edges = seed_graph()
    print("nodes:", {k: v for k, v in nodes.items() if v}, "total:", sum(nodes.values()))
    print("edges:", {k: v for k, v in edges.items() if v}, "total:", sum(edges.values()))
    print("seeded graph 'desk' from clean state (v2 model)")