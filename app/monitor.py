"""R3 — Rules Monitor, the deliberately dumb tier (v2.1 §3/§7).

Simple threshold logic over recent Transaction nodes. It is the trigger, not
the detector: it says "this shape looks wrong here" — nothing more. Proving WHY
is the Investigator's job (C1). Writes ONLY Alert nodes + TRIGGERED_BY links;
every scan journaled.

v2 changes: reads (Account)-[:SENT]->(Transaction)-[:TO]->(Account) chains;
Alert no longer has a status field (dedup on type + target); C (merchant
fan-in) now legitimately FIRES — clearing is downstream, not here.
"""
from datetime import datetime, timedelta

from .graph import get_graph
from .journal import journal

# Dumb visible constants (§7) — tuned so the planted world behaves per §16
FANIN_MIN_SENDERS = 5      # fan-in = ≥5 distinct senders → 1 target in window
FANIN_WINDOW_H = 3
SUB_THRESHOLD_LO = 45000   # §7 SUB_THRESHOLD: inflows within 90–99% of threshold
SUB_THRESHOLD_HI = 49500
SUB_REPEAT_MIN = 3         # same sender→target dripping in that band ×3
SUB_REPEAT_WINDOW_H = 168  # 7 days
VELOCITY_MAX_OUT = 600000  # single account outbound total in window
# ₹6L cap: worst-case noise in 6h = 12 transfers × ₹45k = ₹5.4L < ₹6L → velocity is
# mathematically silent on ANY noise run (live leak found by user testing, Oct 14).
VELOCITY_WINDOW_H = 6

TS_FMT = "%Y-%m-%dT%H:%M"


def _latest_txn_ts(g):
    """Sim clock = newest Transaction. Old-case/seed history falls outside every
    scan window automatically (fixed-format lexicographic timestamps)."""
    row = g.query("MATCH ()-[:SENT]->(t:Transaction) RETURN max(t.ts)").result_set
    ts = row[0][0] if row and row[0] else None
    return datetime.strptime(ts, TS_FMT) if ts else None


def _next_alert_id(g):
    n = g.query("MATCH (a:Alert) RETURN count(a)").result_set[0][0]
    return f"AL-{n + 1:04d}"


def _open_alert(g, atype, target, start, end, txid, extra_props_cypher, params):
    """Create Alert + TRIGGERED_BY(link to the newest triggering Transaction).
    Dedup-guarded: one alert per (type, target). Only Alert nodes written."""
    dup = g.query(
        "MATCH (:Alert {type:$t, target_id:$tid}) RETURN count(*)",
        {"t": atype, "tid": target}).result_set[0][0]
    if dup:
        return None
    aid = _next_alert_id(g)
    g.query(
        f"""MATCH (t:Transaction {{id:$txid}})
            CREATE (al:Alert {{
                id:$aid, type:$t, target_id:$tid,
                window_start:$ws, window_end:$we,
                created_at:$created{extra_props_cypher}}})
            CREATE (al)-[:TRIGGERED_BY {{ts:$we}}]->(t)""",
        {"txid": txid, "t": atype, "tid": target, "aid": aid,
         "ws": start, "we": end,
         "created": datetime.now().isoformat(timespec="seconds"), **params})
    return aid


def _latest_trigger_txn(g, target, frm):
    row = g.query(
        """MATCH (:Account)-[:SENT]->(x:Transaction)-[:TO]->(:Account {id:$tid})
           WHERE x.ts >= $from
           RETURN x.id ORDER BY x.ts DESC LIMIT 1""",
        {"tid": target, "from": frm}).result_set
    return row[0][0] if row else None


def scan_once(g=None):
    """One monitor pass over the recent stream. Returns what it raised."""
    g = g or get_graph()
    now = _latest_txn_ts(g)
    if now is None:
        journal("monitor", "scan", notes="no transactions yet")
        return {"scanned": False, "alerts_created": []}

    def since(hours):
        return (now - timedelta(hours=hours)).strftime(TS_FMT)

    created = []

    # 1) fan-in: many-to-one accumulation into one account (§7)
    rows = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(t:Account)
           WHERE x.ts >= $from
           WITH t, count(DISTINCT s) AS senders, sum(x.amount) AS total
           WHERE senders >= $min
           RETURN t.id, senders, total""",
        {"from": since(FANIN_WINDOW_H), "min": FANIN_MIN_SENDERS}).result_set
    for tid, senders, total in rows:
        txid = _latest_trigger_txn(g, tid, since(FANIN_WINDOW_H))
        aid = _open_alert(
            g, "fan_in", tid, since(FANIN_WINDOW_H), now.strftime(TS_FMT), txid,
            ", sender_count:$sc, total_amount:$sum", {"sc": senders, "sum": total})
        if aid:
            created.append({"id": aid, "type": "fan_in", "target": tid, "senders": senders})

    # 2) SUB_THRESHOLD: >=3 inflows in the 90–99% band from the same sender
    rows = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(t:Account)
           WHERE x.amount >= $lo AND x.amount <= $hi AND x.ts >= $from
           WITH s, t, count(x) AS n, sum(x.amount) AS total
           WHERE n >= $min
           RETURN s.id, t.id, n, total""",
        {"lo": SUB_THRESHOLD_LO, "hi": SUB_THRESHOLD_HI,
         "from": since(SUB_REPEAT_WINDOW_H), "min": SUB_REPEAT_MIN}).result_set
    for sid, tid, n, total in rows:
        txid = _latest_trigger_txn(g, tid, since(SUB_REPEAT_WINDOW_H))
        aid = _open_alert(
            g, "sub_threshold", tid, since(SUB_REPEAT_WINDOW_H), now.strftime(TS_FMT), txid,
            ", pair_source:$src, repeat_count:$n, total_amount:$sum",
            {"src": sid, "n": n, "sum": total})
        if aid:
            created.append({"id": aid, "type": "sub_threshold", "target": tid,
                            "source": sid, "repeats": n})

    # 3) velocity: fast-mover outbound spike
    rows = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)
           WHERE x.ts >= $from
           WITH s, sum(x.amount) AS out
           WHERE out >= $max
           RETURN s.id, out""",
        {"from": since(VELOCITY_WINDOW_H), "max": VELOCITY_MAX_OUT}).result_set
    for sid, out in rows:
        txid = _latest_trigger_txn(g, sid, since(VELOCITY_WINDOW_H))
        aid = _open_alert(
            g, "velocity", sid, since(VELOCITY_WINDOW_H), now.strftime(TS_FMT), txid,
            ", outbound_total:$out", {"out": out})
        if aid:
            created.append({"id": aid, "type": "velocity", "target": sid, "out": out})

    journal("monitor", "scan", alerts=created,
            nodes_written=["Alert"] * len(created),
            edges_written=["TRIGGERED_BY"] * len(created),
            window_now=now.strftime(TS_FMT))
    return {"scanned": True, "alerts_created": created, "as_of": now.strftime(TS_FMT)}