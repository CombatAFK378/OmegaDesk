"""C1 — deterministic signal extractor (v2.1 §7): the 9 signals as plain queries.

For a case: compute each signal from the graph (no LLM anywhere), then write
the Case→EXHIBITS {value, as_of} edges for the ones that scored. Same input
graph → same signals → precedent matching and the Investigator both see a
stable picture.
"""
from datetime import datetime, timedelta

from .graph import get_graph
from .journal import journal

REPORT_THRESHOLD = 50000
BAND_LO, BAND_HI = 45000, 49500          # §7: 90–99% of the reporting line
POLARITY = {                              # the fixed signal catalog (§7)
    "FAN_IN": "aggravating", "SUB_THRESHOLD": "aggravating", "PASS_THROUGH": "aggravating",
    "SHARED_DEVICE": "aggravating", "SHARED_IDENTITY": "aggravating", "NEW_ACCOUNT": "aggravating",
    "RING_MEMBER": "aggravating", "BUSINESS_KYC": "mitigating", "REGULAR_CADENCE": "mitigating",
}
REG_BY_SIGNAL = {  # which Regulation a case's top signal cites (§10)
    "FAN_IN": "R-STRUCT", "SUB_THRESHOLD": "R-STRUCT", "PASS_THROUGH": "R-VELOCITY",
    "SHARED_DEVICE": "R-DEVICE-RING", "SHARED_IDENTITY": "R-DEVICE-RING",
    "NEW_ACCOUNT": "R-STRUCT", "RING_MEMBER": "R-DEVICE-RING",
    "BUSINESS_KYC": "R-MERCH", "REGULAR_CADENCE": "R-MERCH",
}
TS_FMT = "%Y-%m-%dT%H:%M"


def _sim_now(g):
    row = g.query("MATCH ()-[:SENT]->(t:Transaction) RETURN max(t.ts)").result_set
    ts = row[0][0] if row and row[0] else None
    return datetime.strptime(ts, TS_FMT) if ts else None


def _ago(now, **kw):
    return (now - timedelta(**kw)).strftime(TS_FMT)


def extract_signals(case_id, g=None, target=None):
    """Compute the 9 §7 signals for a case; write EXHIBITS edges for the ones
    that fired. `target` = the alert's drain account (the per-target signals —
    FAN_IN/SUB/PASS/CADENCE — are computed against IT, never alphabetical luck)."""
    g = g or get_graph()
    now = _sim_now(g)
    if now is None:
        return []
    as_of = now.strftime(TS_FMT)

    abouts = [r[0] for r in g.query(
        "MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account) RETURN a.id ORDER BY a.id",
        {"cid": case_id}).result_set]
    if not abouts:
        return []
    if target is None:
        tgt_row = g.query(
            "MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert) RETURN al.target_id",
            {"cid": case_id}).result_set
        target = tgt_row[0][0] if tgt_row else abouts[0]
    values = {}

    # 1) FAN_IN — ≥5 distinct senders → target within 24 sim-hours (§7)
    row = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(:Account {id:$t})
           WHERE x.ts >= $from
           RETURN count(DISTINCT s)""",
        {"t": target, "from": _ago(now, hours=24)}).result_set[0][0]
    values["FAN_IN"] = row if row >= 5 else 0

    # 2) SUB_THRESHOLD — same sender→target in the ₹45k-49.5k band ×3+ in 7 days
    row = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(:Account {id:$t})
           WHERE x.amount >= $lo AND x.amount <= $hi AND x.ts >= $from
           WITH s, count(x) AS n ORDER BY n DESC LIMIT 1
           RETURN n""",
        {"t": target, "lo": BAND_LO, "hi": BAND_HI, "from": _ago(now, days=7)}).result_set
    values["SUB_THRESHOLD"] = row[0][0] if row and row[0][0] >= 3 else 0

    # 3) PASS_THROUGH — ≥80% of the 24h window's inflow sent onward within it
    in_row = g.query(
        "MATCH (x:Transaction)-[:TO]->(:Account {id:$t}) WHERE x.ts >= $from RETURN sum(x.amount)",
        {"t": target, "from": _ago(now, hours=24)}).result_set[0][0]
    out_row = g.query(
        "MATCH (s:Account {id:$t})-[:SENT]->(x:Transaction) WHERE x.ts >= $from RETURN sum(x.amount)",
        {"t": target, "from": _ago(now, hours=24)}).result_set[0][0]
    in_amt, out_amt = (in_row or 0), (out_row or 0)
    values["PASS_THROUGH"] = int(100 * out_amt / in_amt) if in_amt and out_amt >= 0.8 * in_amt else 0

    # 4) SHARED_DEVICE — a scope account shares a device with any case-linked account
    row = g.query(
        """MATCH (a:Account)-[:USED_DEVICE]->(:Device)<-[:USED_DEVICE]-(o:Account)
           WHERE a.id IN $ids
           MATCH (c:Case)-[:ABOUT]->(o)
           RETURN count(DISTINCT o)""",
        {"ids": abouts}).result_set[0][0]
    values["SHARED_DEVICE"] = row if row > 0 else 0

    # 5) SHARED_IDENTITY — a scope account is identity-linked to another
    row = g.query(
        """MATCH (a:Account)-[:SAME_IDENTITY]-(o:Account)
           WHERE a.id IN $ids RETURN count(DISTINCT a)""",
        {"ids": abouts}).result_set[0][0]
    values["SHARED_IDENTITY"] = row if row > 0 else 0

    # 6) NEW_ACCOUNT — a scope account opened < 30 days before the window
    row = g.query(
        "MATCH (a:Account) WHERE a.id IN $ids AND a.opened_at >= $cutoff RETURN count(a)",
        {"ids": abouts, "cutoff": (now - timedelta(days=30)).strftime("%Y-%m-%d")}).result_set[0][0]
    values["NEW_ACCOUNT"] = row if row > 0 else 0

    # 7) RING_MEMBER — shares a device with a FROZEN account (freeze = confirmed fraud)
    row = g.query(
        """MATCH (a:Account)-[:USED_DEVICE]->(:Device)<-[:USED_DEVICE]-(o:Account)<-[:FREEZES]-(:FreezeOrder)
           WHERE a.id IN $ids RETURN count(DISTINCT a)""",
        {"ids": abouts}).result_set[0][0]
    values["RING_MEMBER"] = row if row > 0 else 0

    # 8) BUSINESS_KYC — a scope account is run by a KYC-verified merchant
    row = g.query(
        """MATCH (a:Account)-[:OPERATED_BY]->(m:Merchant)
           WHERE a.id IN $ids AND m.business_kyc = true RETURN count(a)""",
        {"ids": abouts}).result_set[0][0]
    values["BUSINESS_KYC"] = row if row > 0 else 0

    # 9) REGULAR_CADENCE — KYC merchant on monthly cadence, all target inflows on one day-of-month
    row = g.query(
        """MATCH (a:Account {id:$t})-[:OPERATED_BY]->(m:Merchant)
           WHERE m.business_kyc = true AND m.registered_cadence = 'monthly'
           MATCH (x:Transaction)-[:TO]->(a)
           RETURN count(x), collect(substring(x.ts, 8, 2))""",
        {"t": target}).result_set
    if row and row[0][0]:
        n, doms = row[0][0], set(row[0][1])
        values["REGULAR_CADENCE"] = n if len(doms) == 1 else 0
    else:
        values["REGULAR_CADENCE"] = 0

    fired = []
    for code, value in values.items():
        if value and value > 0:
            g.query(
                """MATCH (c:Case {id:$cid}), (s:Signal {code:$code})
                   MERGE (c)-[r:EXHIBITS]->(s)
                   SET r.value = $value, r.as_of = $asof""",
                {"cid": case_id, "code": code, "value": value, "asof": as_of})
            fired.append({"code": code, "polarity": POLARITY[code], "value": value})

    journal("signals", "extract", case_id=case_id, as_of=as_of, fired=[s["code"] for s in fired])
    return fired