"""C2 — the desk API (v2.1 §16): everything the UI needs, nothing more.

READ endpoints (no LLM, instant):
  GET  /cases                 — every case, summary row
  GET  /cases/{case_id}       — full detail: scope, signals, decisions + citations
                                (CITES), evidence chain, freeze orders, token spend
  GET  /benchmark/last        — the saved with/without report (§12 proof beat)
WRITE endpoints (LLM/desk actions, authority-guarded as always):
  POST /cases/investigate     — {alert_id} → coordinator pipeline (optional ablated:
                                true runs WITHOUT precedents for the with/without demo)
  POST /cases/{case_id}/override — {analyst_id, action, reason} → the analyst's
                                   correction; becomes precedent for the next twin
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .coordinator import handle_alert, handle_direct_case
from .graph import get_graph
from .journal import JOURNAL_PATH
from .policy import record_override

router = APIRouter(prefix="", tags=["desk"])

REPORT_PATH = Path(__file__).resolve().parent.parent / "benchmark_report.json"


def _rows(q, params=None):
    return get_graph().query(q, params or {}).result_set


# ---------------------------------------------------------------- /cases
@router.get("/cases")
def list_cases():
    """One row per case (no Cartesian fan-out): the alert and the newest
    decision are joined per case in lightweight follow-up queries."""
    rows = _rows(
        """MATCH (c:Case) RETURN c.id, c.status, c.created_at
           ORDER BY c.created_at DESC, c.id LIMIT 50""")
    cases = []
    for cid, status, created in rows:
        al = _rows("""MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert)
                      RETURN al.id, al.type
                      ORDER BY al.created_at LIMIT 1""",
                   {"cid": cid})
        tgt = _rows("""MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert)
                       RETURN al.target_id LIMIT 1""",
                    {"cid": cid})
        dec = _rows("""MATCH (c:Case {id:$cid})<-[:FOR_CASE]-(d:Decision)
                       RETURN d.action ORDER BY d.ts DESC LIMIT 1""",
                    {"cid": cid})
        cases.append({"case_id": cid, "status": status, "created_at": created,
                      "alert_id": al[0][0] if al else None,
                      "alert_type": al[0][1] if al else None,
                      "target": tgt[0][0] if tgt else None,
                      "last_action": dec[0][0] if dec else None})
    return {"cases": cases}


@router.get("/cases/{case_id}")
def case_detail(case_id: str):
    row = _rows("MATCH (c:Case {id:$cid}) RETURN c.id, c.status, c.created_at",
                {"cid": case_id})
    if not row:
        raise HTTPException(404, f"case {case_id!r} not found")

    cid = {"cid": case_id}
    alert = [{"id": r[0], "type": r[1], "target": r[2]}
             for r in _rows("""MATCH (c:Case {id:$cid})-[:FOR_ALERT]->(al:Alert)
                          RETURN al.id, al.type, al.target_id""", cid)]
    scope = [{"account": r[0], "holder": r[1], "kyc": r[2], "opened_at": r[3]}
             for r in _rows("""MATCH (c:Case {id:$cid})-[:ABOUT]->(a:Account)
                              OPTIONAL MATCH (a)-[:OPERATED_BY]->(m:Merchant)
                              OPTIONAL MATCH (a)<-[:OWNS]-(p:Person)
                              RETURN a.id, coalesce(p.name, 'merchant'),
                                     coalesce(m.business_kyc, p.kyc_status), a.opened_at
                              ORDER BY a.id""", cid)]
    signals = [{"code": r[0], "polarity": r[1], "value": r[2], "as_of": r[3]}
               for r in _rows("""MATCH (c:Case {id:$cid})-[ex:EXHIBITS]->(s:Signal)
                                 RETURN s.code, s.polarity, ex.value, ex.as_of
                                 ORDER BY s.polarity, s.code""", cid)]
    decisions = []
    for d_id, d_ts, verdict, action, conf, who, reason in _rows(
            """MATCH (d:Decision)-[:FOR_CASE]->(c:Case {id:$cid})
               RETURN d.id, d.ts, d.verdict, d.action, d.confidence, d.decided_by, d.rationale
               ORDER BY d.ts""", cid):
        cites = [{"decision_id": r[0], "applies": r[1],
                  "distinguishing": json.loads(r[2]) if r[2] else []}
                 for r in _rows("""MATCH (d2:Decision {id:$did})-[c:CITES]->(pd:Decision)
                                   RETURN pd.id, c.applies, c.distinguishing
                                   ORDER BY pd.id""", {"did": d_id})]
        overrides = [{"decision_id": r[0], "reason": r[1]}
                     for r in _rows("""MATCH (ov:Decision)-[o:OVERRIDES]->(d2:Decision {id:$did})
                                       RETURN ov.id, o.reason""", {"did": d_id})]
        decisions.append({"decision_id": d_id, "ts": d_ts, "verdict": verdict,
                          "action": action, "confidence": conf, "decided_by": who,
                          "rationale": reason, "cites": cites, "overridden_by": overrides})
    freezes = [{"order": r[0], "ts": r[1], "account": r[2], "issued_by": r[3]}
               for r in _rows("""MATCH (c:Case {id:$cid})<-[:FOR_CASE]-(d:Decision),
                          (fo:FreezeOrder)-[:ISSUED_BY]->(d),
                          (fo)-[:FREEZES]->(a:Account)
                          RETURN fo.id, fo.ts, a.id, d.id
                          ORDER BY fo.ts""", cid)]
    evidence = [{"query_id": r[0], "tool": r[1], "args": r[2], "node": r[3], "as_of": r[4]}
                for r in _rows("""MATCH (c:Case {id:$cid})-[ev:EVIDENCE]->(n)
                                  RETURN ev.query_id, ev.tool, ev.args, n.id, ev.as_of
                                  ORDER BY ev.query_id""", cid)]
    spend = {"in": 0, "out": 0, "llm_runs": 0}
    if JOURNAL_PATH.exists():
        for line in JOURNAL_PATH.read_text().splitlines():
            try:
                j = json.loads(line)
            except json.JSONDecodeError:
                continue
            # only THIS case's own runs (case-ids repeat across benchmark reruns)
            if (j.get("action") == "llm_run" and j.get("case_id") == case_id
                    and str(j.get("ts", "")) >= str(row[0][2])):
                t = j.get("tokens") or {}
                spend["in"] += t.get("in", 0)
                spend["out"] += t.get("out", 0)
                spend["llm_runs"] += 1
    return {"case_id": case_id, "status": row[0][1], "created_at": row[0][2],
            "alert": alert, "scope": scope, "signals": signals, "decisions": decisions,
            "freeze_orders": freezes, "evidence": evidence, "tokens": spend}


# ---------------------------------------------------------------- investigate
class InvestigateBody(BaseModel):
    alert_id: str | None = None
    about_id: str | None = None
    ablated: bool = False


@router.post("/cases/investigate")
def investigate(body: InvestigateBody):
    if not (body.alert_id or body.about_id):
        raise HTTPException(400, "give alert_id (runs the coordinator pipeline) or about_id (direct case)")
    if body.alert_id:
        exists = _rows("MATCH (a:Alert {id:$id}) RETURN 1", {"id": body.alert_id})
        if not exists:
            raise HTTPException(404, f"alert {body.alert_id!r} not found")
    try:
        if body.alert_id:
            res = handle_alert(body.alert_id, ablated=body.ablated)
        else:
            res = handle_direct_case(f"CASE-{body.about_id}", body.about_id, ablated=body.ablated)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # degrade-safe: never 500 a desk mid-demo
        raise HTTPException(503, f"pipeline unavailable: {str(exc)[:160]}")
    return {**res, "ablated": body.ablated}


# ---------------------------------------------------------------- override
class OverrideBody(BaseModel):
    analyst_id: str
    action: str
    reason: str


@router.post("/cases/{case_id}/override")
def case_override(case_id: str, body: OverrideBody):
    try:
        res = record_override(case_id, body.analyst_id, body.action, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "case_id": case_id, **res,
            "note": "the corrected decision is now precedent for the next twin — and "
                    "the overruled one is never citable again"}


# ---------------------------------------------------------------- benchmark
@router.get("/benchmark/last")
def benchmark_last():
    if not REPORT_PATH.exists():
        raise HTTPException(404, "no benchmark report yet — run scripts/c1_exit_test.py once")
    return json.loads(REPORT_PATH.read_text())