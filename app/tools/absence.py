"""C3 — proof-of-absence (§16 C3): the desk's only honest path to CLEAR.

An accusation needs evidence; a CLEARANCE needs a receipt. This tool runs the
negative checklist — the dangerous connections that are NOT there — and turns
an all-absent pass into a replayable receipt. Code proves it, never the model.

Receipt semantics (the §10 wiring): when every check passes, the flagged
pattern is PROVEN benign (e.g. payroll-into-merchant), so the case's
aggravating shape counts as explained → decide_action(absence_proven=True).
"""
import hashlib
import json
from datetime import datetime, timedelta

from ..graph import get_graph
from ..journal import journal
from .registry import register

TS_FMT = "%Y-%m-%dT%H:%M"


def _sim_now(g):
    row = g.query("MATCH ()-[:SENT]->(t:Transaction) RETURN max(t.ts)").result_set
    ts = row[0][0] if row and row[0] else None
    return datetime.strptime(ts, TS_FMT) if ts else None


def _ago(now, **kw):
    return (now - timedelta(**kw)).strftime(TS_FMT)


@register("read",
          "PROOF-OF-ABSENCE (§16 C3): run the negative checklist on a case — shared "
          "devices with frozen/known-fraud accounts, identity links, counterparty "
          "overlap with frozen accounts, structuring among the payers, velocity. "
          "ALL checks passing = a RECEIPT proving the flagged shape is benign "
          "(e.g. payroll into a merchant). The desk's only honest path to 'clear'.",
          {"case_id": "case id"})
def prove_absence(case_id):
    g = get_graph()
    now = _sim_now(g)
    if now is None:
        return {"receipt": False, "error": "no transactions in the world"}

    cid = {"cid": case_id}
    targets = [r[0] for r in g.query(
        "MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account) RETURN a.id ORDER BY a.id",
        cid).result_set]
    if not targets:
        return {"receipt": False, "error": "case has no scope"}

    checks = []

    def check(code_, question, present):
        checks.append({"id": code_, "question": question,
                       "dangerous": bool(present)})

    # 0) SHAPE sanity: a pass-through IS the suspicious pattern itself — the
    # money was received and forwarded straight out; that is never "benign"
    row = g.query(
        """MATCH (c:Case {id:$cid})-[:EXHIBITS]->(s:Signal {code:'PASS_THROUGH'})
           RETURN s.value""", cid).result_set
    check("pass_through_shape",
          "the money was received and forwarded straight out (pass-through shape)", row)

    # 1) shared device with a FROZEN account (confirmed fraud)
    row = g.query(
        """MATCH (a:Account)-[:USED_DEVICE]->(:Device)<-[:USED_DEVICE]-(o:Account)<-[:FREEZES]-(:FreezeOrder)
           WHERE a.id IN $ids RETURN count(DISTINCT a)""",
        {"ids": targets}).result_set[0][0]
    check("device_ring", "any involved account shares a device with an already-frozen account", row)

    # 2) shared device with any other case-linked account (co-investigated world)
    row = g.query(
        """MATCH (a:Account)-[:USED_DEVICE]->(:Device)<-[:USED_DEVICE]-(o:Account)
           WHERE a.id IN $ids MATCH (:Case)-[:ABOUT]->(o)
           WHERE NOT o.id IN $ids RETURN count(DISTINCT o)""",
        {"ids": targets}).result_set[0][0]
    check("device_buddies", "any involved account shares a device with another under-investigation account", row)

    # 3) identity layering
    row = g.query(
        """MATCH (a:Account)-[:SAME_IDENTITY]-(o:Account)
           WHERE a.id IN $ids RETURN count(DISTINCT a)""",
        {"ids": targets}).result_set[0][0]
    check("identity_link", "any involved account shares KYC-identity details with another", row)

    # 4) counterparty overlap with accounts under any FROZEN decision
    row = g.query(
        """MATCH (a:Account)-[:SENT]->(t:Transaction)-[:TO]->(f:Account)<-[:FREEZES]-(:FreezeOrder)
           WHERE a.id IN $ids
           RETURN count(DISTINCT a)""",
        {"ids": targets}).result_set[0][0]
    check("frozen_counterparty", "any involved account paid an already-frozen account", row)

    # 5) structuring among the payers: one person dripping in the 90-99% band ×3+
    row = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(a:Account)
           WHERE a.id IN $ids AND x.amount >= 45000 AND x.amount <= 49500 AND x.ts >= $from7
           WITH s, a, count(x) AS n WHERE n >= 3
           RETURN count(*)""",
        {"ids": targets, "from7": _ago(now, days=7)}).result_set[0][0]
    check("payer_structuring", "any payer repeatedly dripping just under the reporting line", row)

    # 6) recent velocity out of the receiver
    row = g.query(
        """MATCH (a:Account)-[:SENT]->(x:Transaction)
           WHERE a.id IN $ids AND x.ts >= $from6
           WITH a, sum(x.amount) AS out WHERE out >= 200000
           RETURN count(*)""",
        {"ids": targets, "from6": _ago(now, hours=6)}).result_set[0][0]
    check("velocity", "recent high-speed money moving out of the receiver", row)

    # 7) every payer identity-verified (a clean payroll needs real people)
    row = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(a:Account)
           WHERE a.id IN $ids AND NOT s.id IN $ids
           MATCH (s)<-[:OWNS]-(p:Person)
           WITH DISTINCT s, p
           RETURN count(DISTINCT s) AS senders,
                  sum(CASE WHEN p.kyc_status = true THEN 0 ELSE 1 END) AS unverified""",
        {"ids": targets}).result_set
    senders, unverified = (row[0][0], row[0][1]) if row and row[0] and row[0][0] is not None else (0, None)
    check("payers_verified",
          "a payer shows up without verified identity", None if senders == 0 else unverified)

    receipt = all(not c["dangerous"] for c in checks)
    digest = hashlib.sha256(json.dumps(checks, sort_keys=True).encode()).hexdigest()[:24]
    as_of = now.strftime(TS_FMT)
    result = {
        "receipt": receipt, "case_id": case_id, "as_of": as_of, "digest": digest,
        "checks": [{"id": c["id"], "question": c["question"],
                    "dangerous": c["dangerous"]} for c in checks],
        "plain": ("every dangerous connection was checked and none exists — the flagged "
                  "pattern is explained (receipt stored)")
                  if receipt else
                  ("a dangerous connection exists — no clearance"),
    }
    journal("agent", "prove_absence", case_id=case_id, receipt=receipt,
            digest=digest, as_of=as_of)
    return result