"""C1 — the Coordinator (v2.1 §5): deterministic code, never an LLM.

Alert → Case (scope + signals) → Investigator → policy (with the precedent
safety guard) → Decision / FreezeOrder / evidence links — everything journaled.
The benchmark runner drives this run by run.
"""
import json
from datetime import datetime, timedelta

from .graph import free_id, get_graph
from .investigator import investigate_case
from .journal import journal
from .policy import REG_BY_SIGNAL, decide_action, precedent_action_guard
from .routing import route_case
from .signals import POLARITY, _sim_now, extract_signals
from openai import BadRequestError, OpenAIError

TS_FMT = "%Y-%m-%dT%H:%M"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _expand_scope(case_id, target, since_ts, until_ts, g):
    """Case scope = the funnel, not just the funnel's drain: ABOUT edges to the
    target's counterparties inside the alert window (deterministic, capped 6)."""
    senders = [r[0] for r in g.query(
        """MATCH (s:Account)-[:SENT]->(x:Transaction)-[:TO]->(:Account {id:$tid})
           WHERE x.ts >= $since AND x.ts <= $until AND s.id <> $tid
           WITH DISTINCT s ORDER BY s.id LIMIT 6 RETURN s.id""",
        {"tid": target, "since": since_ts, "until": until_ts}).result_set]
    receivers = [r[0] for r in g.query(
        """MATCH (:Account {id:$tid})-[:SENT]->(x:Transaction)-[:TO]->(o:Account)
           WHERE x.ts >= $since AND x.ts <= $until AND o.id <> $tid
           WITH DISTINCT o ORDER BY o.id LIMIT 6 RETURN o.id""",
        {"tid": target, "since": since_ts, "until": until_ts}).result_set]
    for peer in senders + receivers:
        g.query(
            """MATCH (c:Case {id:$cid}), (a:Account {id:$aid})
               MERGE (c)-[r:ABOUT]->(a)""",
            {"cid": case_id, "aid": peer})


def open_case_for_alert(alert_id, g=None):
    """Alert → Case shell: Case-[:FOR_ALERT]->Alert, Case-[:ABOUT]->scope."""
    g = g or get_graph()
    row = g.query("MATCH (al:Alert {id:$id}) RETURN al.type, al.target_id, "
                  "al.window_start, al.window_end",
                  {"id": alert_id}).result_set
    if not row:
        raise KeyError(f"alert {alert_id!r} not found")
    atype, target, ws, we = row[0]
    seq = free_id(g, "Case", "CASE", g.query("MATCH (c:Case) RETURN count(c)").result_set[0][0] + 1)
    case_id = f"CASE-{seq:04d}"
    created = _now()
    g.query(
        """MATCH (al:Alert {id:$aid}), (target:Account {id:$tid})
           CREATE (c:Case {id:$cid, status:'open', created_at:$created})
           CREATE (c)-[:FOR_ALERT {ts:$created}]->(al)
           CREATE (c)-[:ABOUT {ts:$created}]->(target)""",
        {"aid": alert_id, "tid": target, "cid": case_id, "created": created})
    _expand_scope(case_id, target, ws or '2026-01-01T00:00', we or '2026-01-02T00:00', g)
    journal("coordinator", "case_opened", case_id=case_id, alert_id=alert_id,
            target=target, scope_expanded=True)
    return {"case_id": case_id, "target": target, "alert_type": atype}


def open_case_direct(case_id, about_id, g=None):
    """A case without an alert (the benchmark's E-trap path). Scope expands
    over the 24h window before the latest transaction."""
    g = g or get_graph()
    created = _now()
    g.query("CREATE (c:Case {id:$cid, status:'open', created_at:$created})",
            {"cid": case_id, "created": created})
    g.query("MATCH (c:Case {id:$cid}), (a:Account {id:$aid}) "
            "CREATE (c)-[:ABOUT {ts:'2026-01-01'}]->(a)",
            {"cid": case_id, "aid": about_id})
    sim_now = _sim_now(g)
    if sim_now:
        _expand_scope(case_id, about_id,
                      (sim_now - timedelta(hours=24)).strftime(TS_FMT),
                      sim_now.strftime(TS_FMT), g)
    journal("coordinator", "case_opened", case_id=case_id, target=about_id,
            alert_id=None, scope_expanded=True)
    return {"case_id": case_id, "target": about_id, "alert_type": None}


def _case_target(g, case_id):
    """The alert's target account = the pattern's drain (never alphabetical luck)."""
    row = g.query(
        "MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert) RETURN al.target_id",
        {"cid": case_id}).result_set
    if row:
        return row[0][0]
    row = g.query("MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account) RETURN a.id LIMIT 1",
                  {"cid": case_id}).result_set
    return row[0][0] if row else None


def _cited_precedent_actions(g, precedents):
    """For the precedent guard: which ACTION each applies-true precedent holds."""
    actions = []
    for p in precedents or []:
        if not p.get("applies"):
            continue
        row = g.query("MATCH (d:Decision {id:$id}) RETURN d.action",
                      {"id": p.get("decision_id")}).result_set
        if row:
            actions.append({"decision_id": p.get("decision_id"), "action": row[0][0]})
    return actions


def _has_mitigating_precedent(g, precedents):
    """§10's freeze gate hinges on an applicable MITIGATING precedent (a cited
    precedent whose case exhibits a mitigating signal) — not raw signals."""
    for p in precedents or []:
        if not p.get("applies"):
            continue
        row = g.query(
            """MATCH (d:Decision {id:$id})-[:FOR_CASE]->(:Case)-[:EXHIBITS]->(s:Signal)
               WHERE s.polarity = 'mitigating' RETURN count(s)""",
            {"id": p.get("decision_id")}).result_set[0][0]
        if row:
            return True
    return False


def _evidence_node(call):
    """Best node a tool-call proves: precedents → decision, traces → txn,
    shared entities → device, context → nothing (lives on the case)."""
    tool, res = call.get("tool"), call.get("result") or {}
    if tool == "find_precedents":
        prec = (res.get("precedents") or [None])[0]
        return prec["decision_id"] if prec else None
    if tool == "trace_money_path":
        paths = res.get("paths") or []
        legs = (paths[0].get("legs") if paths else None) or []
        return legs[0].get("txn") if legs and legs[0].get("txn") else None
    if tool == "find_shared_entities":
        devs = res.get("shared_devices") or []
        return devs[0]["device"] if devs else None
    return None


def _run_pipeline(case_id, ablated, client, g):
    """Signals → Investigator → policy guard → writes. One case, one run."""
    from .tools.registry import set_memory_ablation
    target = _case_target(g, case_id)
    fired = extract_signals(case_id, g, target=target)
    set_memory_ablation(ablated)   # §12: the with/without switch, per run
    try:
        inv = investigate_case(case_id, client)
    except (BadRequestError, OpenAIError) as exc:   # LLM hiccup → degrade to a SAFE decision
        set_memory_ablation(None)
        inv = {"verdict": "unclear", "confidence": 0.0, "evidence": [], "precedents": [],
               "rationale": f"investigator unavailable: {str(exc)[:120]}",
               "tool_sequence": [], "tokens": {"in": 0, "out": 0}, "calls": []}
    set_memory_ablation(None)

    cited = _cited_precedent_actions(g, inv.get("precedents"))
    mitigation = _has_mitigating_precedent(g, inv.get("precedents"))
    has_mitigating_signal = any(s["polarity"] == "mitigating" for s in fired)
    # proof-of-absence (§16 C3): a DETERMINISTIC receipt, not a model judgment —
    # the pipeline runs it itself when the case carries mitigating evidence;
    # the agent may also call it via its tools (that result merges here).
    from .tools.absence import prove_absence as _prove
    receipt = next((c["result"] for c in inv.get("calls", [])
                    if c.get("tool") == "prove_absence" and (c.get("result") or {}).get("receipt")),
                   None)
    if receipt is None and has_mitigating_signal:
        result = _prove(case_id)
        receipt = result if result and result.get("receipt") else None
    absence_proven = bool(receipt)
    has_aggravating = any(s["polarity"] == "aggravating" for s in fired) and not absence_proven
    # twin-rule inputs (§11 C′/E vs D): which cited decisions are corrections,
    # and did the investigator prove a CATALOG-CODE distinction
    model_precedents = inv.get("precedents") or []
    cited_ids = [p.get("decision_id") for p in model_precedents if p.get("decision_id")]
    corrected_ids = set()
    if cited_ids:
        corrected_ids = {r[0] for r in g.query(
            "MATCH (d:Decision)-[:OVERRIDES]->() WHERE d.id IN $ids RETURN d.id",
            {"ids": cited_ids}).result_set}
    valid_distinguish = any(
        not p.get("applies") and
        any(s in POLARITY for s in p.get("distinguishing_signals") or [])
        for p in model_precedents)
    action = decide_action(inv.get("confidence", 0.0),
                           has_mitigating=has_mitigating_signal if absence_proven else mitigation,
                           has_aggravating=has_aggravating, absence_proven=absence_proven)
    action = precedent_action_guard(action, cited, absence_proven=absence_proven,
                                    corrected_cited=bool(corrected_ids),
                                    valid_distinguish=valid_distinguish)
    verdict = inv.get("verdict", "unclear")
    if action == "clear":
        verdict = "legit"   # code's authority: a receipt-backed clearance IS a legit finding

    top = next((s["code"] for s in fired if s["polarity"] == "aggravating"), None)
    reg = REG_BY_SIGNAL.get(top) if top else None  # citation (§10)
    seq = free_id(g, "Decision", "D", g.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] + 1)
    dec_id = f"D-{seq:04d}"
    g.query(
        """MATCH (c:Case {id:$cid})
           CREATE (dec:Decision {id:$did, ts:$ts, verdict:$verdict, action:$action,
                     confidence:$conf, decided_by:'agent', rationale:$reason,
                     policy_version:'v2.1'})-[:FOR_CASE {ts:$ts}]->(c)""",
        {"cid": case_id, "did": dec_id, "ts": _now(), "verdict": verdict,
         "action": action, "conf": inv.get("confidence", 0.0),
         "reason": inv.get("rationale", "")})
    # citation record per §6: Decision-[:CITES {applies, distinguishing}]->precedent-Decision
    overruled = {r[0] for r in g.query(
        "MATCH (d:Decision)<-[:OVERRIDES]-() RETURN d.id").result_set}
    for p in inv.get("precedents", []):
        pid = p.get("decision_id")
        if not pid or pid in overruled:   # an overruled decision is never cited, even if the model names it
            continue
        g.query(
            """MATCH (dec:Decision {id:$did}), (pd:Decision {id:$pid})
               CREATE (dec)-[:CITES {ts:$ts, applies:$ap,
                          distinguishing:$dist}]->(pd)""",
            {"did": dec_id, "pid": pid, "ts": _now(),
             "ap": bool(p.get("applies")),
             "dist": json.dumps(p.get("distinguishing_signals") or [])})
    if reg:
        g.query("MATCH (dec:Decision {id:$did}), (r:Regulation {id:$rid}) "
                "CREATE (dec)-[:APPLIED_POLICY {ts:'2026-01-01'}]->(r)",
                {"did": dec_id, "rid": reg})
    # replayable evidence chain: every tool call becomes a stored EVIDENCE edge
    sim_now = _sim_now(g)
    asof = sim_now.strftime(TS_FMT) if sim_now else '2026-01-01'
    for call in inv.get("calls", []):
        if call.get("error") or not call.get("result"):
            continue
        node_id = _evidence_node(call)
        if not node_id:
            continue
        g.query(
            """MATCH (c:Case {id:$cid}), (n {id:$nid})
               CREATE (c)-[:EVIDENCE {query_id:$qid, tool:$tool, args:$args,
                          snapshot:$snap, as_of:$asof}]->(n)""",
            {"cid": case_id, "nid": node_id, "qid": call["query_id"],
             "tool": call["tool"], "args": json.dumps(call["args"], default=str),
             "snap": json.dumps(call["result"], default=str)[:200], "asof": asof})
    if action == "freeze" and target:
        # freeze the alert's drain only — the expanded scope holds its (possibly
        # innocent) payers, and a freeze marks an account as confirmed fraud
        g.query(
            """MATCH (c:Case {id:$cid})-[:ABOUT]->(target:Account {id:$tid}), (dec:Decision {id:$did})
               CREATE (fo:FreezeOrder {id:$fid, ts:$ts})
               CREATE (fo)-[:FREEZES {ts:$ts}]->(target)
               CREATE (fo)-[:ISSUED_BY {ts:$ts}]->(dec)""",
            {"cid": case_id, "tid": target, "did": dec_id, "fid": f"FO-{seq:04d}", "ts": _now()})
    if receipt:   # the receipt is stored ON the decision; only a clearance closes the case
        g.query(
            """MATCH (d:Decision {id:$did}), (c:Case {id:$cid})
               SET d.receipt_digest = $dg, d.receipt_as_of = $rasof,
                   d.receipt_checks = $rchecks""" + ("""
               , c.status = 'closed', c.closed_at = $ts""" if action == "clear" else ""),
            {"did": dec_id, "cid": case_id, "dg": receipt["digest"],
             "rasof": receipt["as_of"], "ts": _now(),
             "rchecks": json.dumps(receipt["checks"])})
    routed = route_case(case_id, fired, g)
    journal("policy", "decision", case_id=case_id, decision_id=dec_id, verdict=verdict,
            outcome=action, confidence=inv.get("confidence"),
            mitigating_precedent=mitigation, cited=cited, tokens=inv.get("tokens"),
            absence_receipt=bool(receipt), assigned_to=routed["analyst"])
    return {"case_id": case_id, "dec_id": dec_id, "verdict": verdict, "action": action,
            "confidence": inv.get("confidence", 0.0), "cited": cited,
            "absence_receipt": receipt, "assigned_to": routed["analyst"],
            "desk": routed["desk"],
            "cited_all": sorted({p.get("decision_id") for p in inv.get("precedents", [])
                                 if p.get("decision_id")}),
            "tool_sequence": inv.get("tool_sequence"), "tokens": inv.get("tokens"),
            "signals": fired}


def handle_alert(alert_id, ablated=False, client=None, g=None):
    """Full deterministic pipeline for one alert; the only entry callers need."""
    g = g or get_graph()
    meta = open_case_for_alert(alert_id, g)
    return _run_pipeline(meta["case_id"], ablated, client, g)


def handle_direct_case(case_id, about_id, ablated=False, client=None, g=None):
    """Same pipeline for a case that had no monitor alert (benchmarks' E path)."""
    g = g or get_graph()
    open_case_direct(case_id, about_id, g)
    return _run_pipeline(case_id, ablated, client, g)