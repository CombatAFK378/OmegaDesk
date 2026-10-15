"""R4 — Graph Tool Layer, v2 (v2.1 §9): the core-4 read tools + whitelist.

The Investigator (the ONLY LLM loop) calls exactly these:
  get_case_context · find_precedents · trace_money_path · find_shared_entities
plus the whitelisted read-only Cypher escape hatch.

Demoted per §15 (logic kept here, NOT registered — re-attach at C3/C4):
get_entity_profile, find_fan_in, detect_communities, cite_policy.
`prior_cases` is folded into find_precedents (§8). Agent authority + journaling
live in registry.run_tool. Nothing here calls an LLM.
"""
import re
from collections import defaultdict
from datetime import datetime, timedelta

from ..graph import get_graph
from .registry import register

# ---------------------------------------------------------------------------
# run_cypher_readonly whitelist — bounded, shape-approved, logged
# ---------------------------------------------------------------------------
FORBIDDEN_TOKENS = ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE", "CALL",
                    "INDEX", "DROP", "LOAD", "FOREACH")
MAX_QUERY_CHARS = 1000
MAX_LIMIT = 100

APPROVED_SHAPES = [
    re.compile(r"^MATCH \(a:Account \{id:\$\w+\}\) RETURN a(\.id)?( LIMIT \d+)?$"),
    re.compile(r"^MATCH \(a:Account \{id:'[^']*'\}\)-\[:SENT\]->\(t:Transaction\)-\[:TO\]->\(m:Account\) "
               r"RETURN a\.id, t\.id, m\.id( LIMIT \d+)?$"),
    re.compile(r"^MATCH \(p:Person\) WHERE p\.name CONTAINS \$q "
               r"RETURN p\.name, p\.kyc_status( LIMIT \d+)?$"),
]


def _sim_now(g):
    row = g.query("MATCH ()-[:SENT]->(t:Transaction) RETURN max(t.ts)").result_set
    ts = row[0][0] if row and row[0] else None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M") if ts else None


@register("read", "Escalation hatch: run a bounded, WHITELISTED read-only Cypher "
                 "pattern. Anything writing, removing, or procedural is rejected.",
          {"pattern_cypher": "cypher string", "params": "dict, optional"})
def run_cypher_readonly(pattern_cypher, params=None):
    q = " ".join(str(pattern_cypher).split())
    if len(q) > MAX_QUERY_CHARS:
        raise PermissionError(f"query too long ({len(q)} > {MAX_QUERY_CHARS}) — not whitelisted")
    up = q.upper()
    if any(tok in up for tok in FORBIDDEN_TOKENS):
        raise PermissionError(f"non-whitelisted Cypher (write/procedure keyword): {pattern_cypher!r}")
    if not any(rx.match(q) for rx in APPROVED_SHAPES):
        raise PermissionError(f"Cypher pattern not in whitelist: {pattern_cypher!r}")
    if "LIMIT" not in up:
        q += f" LIMIT {MAX_LIMIT}"
    rows = get_graph().query(q, params or {}).result_set
    return {"query": q, "rows": rows}


@register("read", "Everything known about a case, compact: scope accounts + holder KYC, "
                  "computed signals with polarity, the triggering alert, latest "
                  "transactions, and the decisions already on the case.",
          {"case_id": "case id"})
def get_case_context(case_id):
    g = get_graph()
    case = g.query("MATCH (c:Case {id:$cid}) RETURN c.id, c.status, c.created_at",
                   {"cid": case_id}).result_set
    if not case:
        return {"found": False, "case_id": case_id}
    ctx = {"found": True, "case_id": case[0][0], "status": case[0][1], "created_at": case[0][2]}

    accounts = []
    for (aid,) in g.query(
            "MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account) RETURN a.id ORDER BY a.id",
            {"cid": case_id}).result_set:
        acc = {"id": aid}
        holder = g.query(
            "MATCH (p:Person)-[:OWNS]->(:Account {id:$aid}) RETURN p.name, p.kyc_status",
            {"aid": aid}).result_set
        acc["holder"] = {"name": holder[0][0], "kyc": holder[0][1]} if holder else None
        inflow = g.query(
            "MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(:Account {id:$aid}) "
            "RETURN count(t), sum(t.amount)", {"aid": aid}).result_set[0]
        acc["money_in"] = {"count": inflow[0], "total": inflow[1] or 0}
        recent = g.query(
            "MATCH (s:Account)-[:SENT]->(t:Transaction)-[:TO]->(:Account {id:$aid}) "
            "RETURN t.id, t.amount, t.ts ORDER BY t.ts DESC LIMIT 3",
            {"aid": aid}).result_set
        acc["recent_in"] = [{"txn": r[0], "amount": r[1], "ts": r[2]} for r in recent]
        merch = g.query(
            "MATCH (:Account {id:$aid})-[:OPERATED_BY]->(m:Merchant) "
            "RETURN m.business_kyc, m.registered_cadence", {"aid": aid}).result_set
        acc["merchant"] = ({"business_kyc": merch[0][0], "cadence": merch[0][1]}
                           if merch else None)
        accounts.append(acc)
    ctx["accounts"] = accounts

    ctx["signals"] = [
        {"code": r[0], "polarity": r[1], "value": r[2]}
        for r in g.query(
            "MATCH (c:Case {id:$cid})-[e:EXHIBITS]->(s:Signal) "
            "RETURN s.code, s.polarity, e.value", {"cid": case_id}).result_set]
    alert = g.query(
        "MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert) "
        "RETURN al.id, al.type, al.target_id", {"cid": case_id}).result_set
    ctx["alert"] = {"id": alert[0][0], "type": alert[0][1], "target": alert[0][2]} if alert else None
    ctx["decisions"] = [
        {"id": r[0], "verdict": r[1], "action": r[2], "confidence": r[3], "ts": r[4],
         "overruled_by": r[5]}
        for r in g.query(
            "MATCH (d:Decision)-[:FOR_CASE]->(c:Case {id:$cid}) "
            "OPTIONAL MATCH (d)<-[:OVERRIDES]-(ov:Decision) "
            "RETURN d.id, d.verdict, d.action, d.confidence, d.ts, ov.id",
            {"cid": case_id}).result_set]
    return ctx


@register("read", "PRECEDENT LOOKUP (§8 — the core memory mechanism): past "
                  "Decisions on cases sharing signals with this one, ranked by "
                  "signal overlap + entity proximity (shared device, counterparty, "
                  "identity or merchant). OVERRULED decisions are never returned.",
          {"case_id": "case id", "limit": "int, default 3"})
def find_precedents(case_id, limit=3):
    g = get_graph()
    case = g.query("MATCH (c:Case {id:$cid}) RETURN c.id, c.created_at",
                   {"cid": case_id}).result_set
    if not case:
        return {"found": False, "case_id": case_id, "precedents": []}
    case_created = case[0][1]

    # exclusions first (§8): overruled precedent is never cited
    overruled = {r[0] for r in
                 g.query("MATCH (d:Decision)<-[:OVERRIDES]-() RETURN d.id").result_set}

    rows = g.query(
        """MATCH (c:Case {id:$cid})-[:EXHIBITS]->(s:Signal)
               <-[:EXHIBITS]-(pc:Case)<-[:FOR_CASE]-(d:Decision)
           WHERE pc.created_at < $created
           RETURN d.id, pc.id, collect(s.code), pc.created_at""",
        {"cid": case_id, "created": case_created}).result_set

    cands = []
    for did, pcid, shared, pc_created in rows:
        if did in overruled:
            continue
        drow = g.query(
            "MATCH (d:Decision {id:$did}) RETURN d.verdict, d.action, d.confidence, d.ts, "
            "d.rationale", {"did": did}).result_set[0]
        prox = g.query(
            """MATCH (a1:Account)<-[:ABOUT]-(c:Case {id:$cid}),
                   (a2:Account)<-[:ABOUT]-(pc:Case {id:$pcid})
               WHERE a1 = a2
                  OR (a1)-[:USED_DEVICE]->(:Device)<-[:USED_DEVICE]-(a2)
                  OR (a1)-[:SENT]->(:Transaction)-[:TO]->(a2)
                  OR (a2)-[:SENT]->(:Transaction)-[:TO]->(a1)
                  OR (a1)-[:SAME_IDENTITY]-(a2)
                  OR (a1)-[:OPERATED_BY]->(:Merchant)<-[:OPERATED_BY]-(a2)
               RETURN count(DISTINCT a2)""",
            {"cid": case_id, "pcid": pcid}).result_set
        proximity = sum(r[0] for r in prox) > 0
        cands.append({
            "decision_id": did, "case_id": pcid,
            "verdict": drow[0], "action": drow[1], "confidence": drow[2],
            "decided_at": drow[3], "rationale": drow[4],
            "shared_signals": shared, "shared_count": len(shared),
            "proximity": proximity, "pc_created": pc_created,
        })
    # §8 ranking: signal overlap first, then entity proximity, then recency
    cands.sort(key=lambda c: c["pc_created"], reverse=True)
    cands.sort(key=lambda c: (-c["shared_count"], 0 if c["proximity"] else 1))
    top = cands[:max(1, int(limit))]
    for c in top:
        c.pop("pc_created", None)
    return {"found": True, "case_id": case_id, "candidates_seen": len(cands),
            "excluded_overruled": len(overruled), "precedents": top}


@register("read", "Walk the money: SENT→Transaction→TO chains between two accounts "
                  "(bounded hops, optional as-of). Every path comes from the graph "
                  "— never invented.",
          {"src": "account id", "dst": "account id", "max_hops": "int ≤6",
           "as_of": "timestamp, optional — replay as of a past moment"})
def trace_money_path(src, dst, max_hops=4, as_of=None):
    g = get_graph()
    mh = max(1, min(int(max_hops), 6))
    rows = g.query(
        f"""MATCH p = (a:Account {{id:$s}})-[:SENT|TO*1..{2 * mh}]->(b:Account {{id:$d}})
            RETURN [n IN nodes(p) | n.id],
                   [n IN nodes(p) | labels(n)[0]],
                   [r IN relationships(p) | type(r)]""",
        {"s": src, "d": dst}).result_set
    # validate the strict alternation Account-SENT->Transaction-TO->Account...
    txn_ids = set()
    valid = []
    for ids, labels, rels in rows:
        ok = (len(ids) == len(rels) + 1 and len(ids) % 2 == 1
              and rels[0] == "SENT"
              and all(r == "TO" if i % 2 else r == "SENT" for i, r in enumerate(rels))
              and all(labels[i] == "Transaction" for i in range(1, len(ids), 2)))
        if not ok:
            continue
        txn_ids.update(ids[1::2])
        valid.append((ids, rels))
    amounts = {}
    if txn_ids:
        for tid, amount, ts in g.query(
                "MATCH (t:Transaction) WHERE t.id IN $ids RETURN t.id, t.amount, t.ts",
                {"ids": list(txn_ids)}).result_set:
            amounts[tid] = (amount, ts)
    paths = []
    for ids, rels in valid:
        if as_of and any(amounts[t][1] > as_of for t in ids[1::2] if t in amounts):
            continue  # replayed strictly before the as-of moment
        legs = [{"from": ids[i], "txn": ids[i + 1], "to": ids[i + 2],
                 "amount": amounts.get(ids[i + 1], (None,))[0],
                 "ts": amounts.get(ids[i + 1], (None, None))[1]}
                for i in range(0, len(ids) - 1, 2)]
        accounts = [ids[i] for i in range(0, len(ids), 2)]
        paths.append({"hops": len(legs), "path": accounts, "legs": legs,
                      "total_amount": sum(l["amount"] or 0 for l in legs)})
    paths.sort(key=lambda p: p["path"])
    return {"src": src, "dst": dst, "count": len(paths), "paths": paths,
            "as_of": as_of}


@register("read", "Overlap among suspects: shared devices, SAME_IDENTITY links, "
                  "shared counterparties, shared merchant. (IP only if modelled — §6 note.)",
          {"account_ids": "list of account ids"})
def find_shared_entities(account_ids):
    g = get_graph()
    devices = g.query(
        """MATCH (a:Account)-[:USED_DEVICE]->(d:Device)
           WHERE a.id IN $ids
           WITH d, collect(a.id) AS users
           WHERE size(users) >= 2
           RETURN d.id, d.fingerprint, users""",
        {"ids": account_ids}).result_set
    identity = g.query(
        """MATCH (a:Account)-[:SAME_IDENTITY]-(b:Account)
           WHERE a.id IN $ids AND b.id IN $ids AND a.id < b.id
           RETURN a.id, b.id""",
        {"ids": account_ids}).result_set
    counterparties = g.query(
        """MATCH (a:Account)-[:SENT]->(:Transaction)-[:TO]->(m:Account)
           WHERE a.id IN $ids
           WITH m, collect(DISTINCT a.id) AS senders
           WHERE size(senders) >= 2
           RETURN m.id, senders""",
        {"ids": account_ids}).result_set
    merchants = g.query(
        """MATCH (a:Account)-[:OPERATED_BY]->(m:Merchant)
           WHERE a.id IN $ids
           WITH m, collect(a.id) AS accounts
           WHERE size(accounts) >= 2
           RETURN m.id, accounts""",
        {"ids": account_ids}).result_set
    return {"accounts": account_ids,
            "shared_devices": [{"device": r[0], "fingerprint": r[1], "used_by": r[2]} for r in devices],
            "identity_pairs": [[r[0], r[1]] for r in identity],
            "shared_counterparties": [{"account": r[0], "senders": r[1]} for r in counterparties],
            "shared_merchants": [{"merchant": r[0], "accounts": r[1]} for r in merchants],
            "note": "IP not modelled (§6: optional)"}


# ---------------------------------------------------------------------------
# DEMOTED (§15) — logic kept, re-register at C3/C4
# ---------------------------------------------------------------------------
def get_entity_profile(entity_id):
    """v2 profile; demoted per §15 (folded into get_case_context at C1)."""
    g = get_graph()
    rows = g.query("MATCH (n {id:$eid}) RETURN labels(n), properties(n)",
                   {"eid": entity_id}).result_set
    if not rows:
        return {"found": False, "id": entity_id}
    labels, props = rows[0]
    p = {"found": True, "id": entity_id, "labels": labels, "properties": props}
    out = g.query(
        "MATCH (n:Account {id:$eid})-[:SENT]->(t:Transaction)-[:TO]->(m:Account) "
        "RETURN count(t), sum(t.amount), collect(DISTINCT m.id)", {"eid": entity_id}).result_set[0]
    inn = g.query(
        "MATCH (n:Account)<-[:TO]-(t:Transaction)<-[:SENT]-(s:Account) "
        "RETURN count(t), sum(t.amount), collect(DISTINCT s.id)", {"eid": entity_id}).result_set[0]
    p["money_out"] = {"count": out[0], "total": out[1] or 0, "counterparties": out[2]}
    p["money_in"] = {"count": inn[0], "total": inn[1] or 0, "counterparties": inn[2]}
    p["devices"] = g.query(
        "MATCH (:Account {id:$eid})-[:USED_DEVICE]->(d:Device) RETURN d.id, d.fingerprint",
        {"eid": entity_id}).result_set
    holder = g.query(
        "MATCH (p:Person)-[:OWNS]->(:Account {id:$eid}) RETURN p.name, p.kyc_status",
        {"eid": entity_id}).result_set
    p["holder"] = {"name": holder[0][0], "kyc": holder[0][1]} if holder else None
    frozen = g.query(
        "MATCH (fo:FreezeOrder)-[:FREEZES]->(:Account {id:$eid}) RETURN collect(fo.id)",
        {"eid": entity_id}).result_set[0][0]
    p["frozen_by"] = frozen  # status is DERIVED from FreezeOrder events (§6 rules)
    if "Device" in labels:
        p["accounts_on_device"] = g.query(
            "MATCH (a:Account)-[:USED_DEVICE]->(:Device {id:$eid}) RETURN collect(a.id)",
            {"eid": entity_id}).result_set[0][0]
    return p


def find_fan_in(target, window_hours=24):
    """§7 FAN_IN probe; demoted (the monitor computes it as CODE)."""
    g = get_graph()
    now = _sim_now(g)
    if now is None:
        return {"target": target, "senders": 0, "total": 0}
    frm = (now - timedelta(hours=int(window_hours))).strftime("%Y-%m-%dT%H:%M")
    row = g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(t:Account {id:$tid})
           WHERE x.ts >= $from
           RETURN count(DISTINCT s), sum(x.amount), collect(DISTINCT s.id)""",
        {"tid": target, "from": frm}).result_set[0]
    return {"target": target, "window_hours": window_hours,
            "as_of": now.strftime("%Y-%m-%dT%H:%M"),
            "senders": row[0], "total": row[1] or 0, "senders_list": row[2]}


def detect_communities(window_hours=48):
    """Union-find over the recent transfer graph; demoted per §15 (C3 adds
    FalkorDB algorithms: WCC/CDLP/betweenness)."""
    g = get_graph()
    now = _sim_now(g)
    if now is None:
        return {"components": []}
    frm = (now - timedelta(hours=int(window_hours))).strftime("%Y-%m-%dT%H:%M")
    edges = g.query(
        "MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(t:Account) "
        "WHERE x.ts >= $from RETURN s.id, t.id", {"from": frm}).result_set

    parent = {}
    def find(x):
        root = x
        while parent.get(root, root) != root:
            root = parent[root]
        while parent.get(x, x) != root:
            parent[x], x = root, parent[x]
        return root
    for a, b in edges:
        parent.setdefault(a, a), parent.setdefault(b, b)
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups = defaultdict(list)
    for node in parent:
        groups[find(node)].append(node)
    out = []
    for members in groups.values():
        if len(members) < 3:
            continue
        shared = g.query(
            """MATCH (m:Account)-[:USED_DEVICE]->(d:Device)
               WHERE m.id IN $members
               WITH d, collect(m.id) AS users
               WHERE size(users) >= 2
               RETURN d.id, users""",
            {"members": members}).result_set
        out.append({"members": sorted(members), "size": len(members),
                    "shared_devices": [{"device": r[0], "used_by": r[1]} for r in shared]})
    out.sort(key=lambda c: (-c["size"], c["members"][0]))
    return {"window_hours": window_hours, "components": out}


def cite_policy(pattern_type):
    """§7 signal catalogue → Regulation nodes; demoted (the policy engine reads
    Regulation directly as code, §9)."""
    g = get_graph()
    keywords = {
        "structuring": ["STRUCT"], "sub_threshold": ["STRUCT"],
        "fan_in": ["STRUCT"], "velocity": ["VELOCITY"], "pass_through": ["VELOCITY"],
        "device_ring": ["DEVICE-RING"], "layering": ["DEVICE-RING"],
        "business_kyc": ["MERCH"], "regular_cadence": ["MERCH"],
    }.get(pattern_type, [str(pattern_type).upper()])
    rows = g.query(
        """MATCH (r:Regulation)
           WHERE any(k IN $keys WHERE r.id = k OR toUpper(r.title) CONTAINS k
                     OR toUpper(r.clause) CONTAINS k OR r.section = k)
           RETURN r.id, r.title, r.section, r.clause""",
        {"keys": keywords}).result_set
    return {"pattern_type": pattern_type,
            "regulations": [{"id": r[0], "title": r[1], "section": r[2], "clause": r[3]} for r in rows]}