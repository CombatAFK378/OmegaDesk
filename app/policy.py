"""C1 — policy engine (v2.1 §10): DETERMINISTIC action decisions — code, not a model.

- decide_action: the §10 table (freeze/escalate/monitor/clear)
- precedent_action_guard: the override safety rule — a clearance that exists
  only because an override-precedent suggests it can never auto-clear (and
  never auto-freeze); those route to human review.
- record_override: the analyst's own correction of a case's decision (writes
  Decision + OVERRIDES + MADE_BY — the thing the NEXT case cites).
"""
from datetime import datetime

from .graph import get_graph
from .journal import journal

FREEZE_MIN = 0.85
ESCALATE_MIN = 0.60

ACTIONS = ("freeze", "escalate", "monitor", "clear")

# which Regulation a signal's case cites (§10) — single source for coordinator
REG_BY_SIGNAL = {
    "FAN_IN": "R-STRUCT", "SUB_THRESHOLD": "R-STRUCT", "PASS_THROUGH": "R-VELOCITY",
    "SHARED_DEVICE": "R-DEVICE-RING", "SHARED_IDENTITY": "R-DEVICE-RING",
    "NEW_ACCOUNT": "R-STRUCT", "RING_MEMBER": "R-DEVICE-RING",
    "BUSINESS_KYC": "R-MERCH", "REGULAR_CADENCE": "R-MERCH",
}


def decide_action(confidence, has_mitigating=False, has_aggravating=True,
                  absence_proven=False):
    """§10 table:
    - clear only with proof-of-absence + mitigating + zero aggravating
    - ≥0.85 → freeze, UNLESS an applicable mitigating precedent exists → escalate
    - 0.60–0.85 → escalate (human review)
    - <0.60 → monitor only
    """
    if absence_proven and has_mitigating and not has_aggravating:
        return "clear"
    if confidence >= FREEZE_MIN:
        return "escalate" if has_mitigating else "freeze"
    if confidence >= ESCALATE_MIN:
        return "escalate"
    return "monitor"


def precedent_action_guard(action, cited_precedents, absence_proven=False,
                           corrected_cited=False, valid_distinguish=False):
    """§10/§11 safety rules, deterministic:
    - 'clear' can never ride a precedent (needs own absence-proof)
    - a freeze suggested beside an override-cleared twin → escalate (pillar 4:
      overrides only move actions toward human review)
    - BUT a catalog-code distinction (e.g. BUSINESS_KYC absent where the cleared
      twin had it) lets evidence decide — §11's D story."""
    cited_actions = {p.get("action", "") for p in (cited_precedents or [])}
    if action == "clear" and (cited_precedents or not absence_proven):
        return "escalate"
    if action in ("clear", "freeze") and "clear" in cited_actions and not absence_proven:
        return "escalate"
    if action == "freeze" and corrected_cited and not valid_distinguish:
        return "escalate"
    return action


def record_override(case_id, analyst_id, action, reason, g=None):
    """The analyst's correction of a case's decision. The overridden decision
    gains an incoming OVERRIDES edge → it is never citable as precedent again."""
    g = g or get_graph()
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if not str(reason or "").strip():
        raise ValueError("an override without a written reason is not recorded (§10)")
    # the decision to correct = the newest one on the case that has no override yet
    row = g.query(
        "MATCH (c:Case {id:$cid})<-[:FOR_CASE]-(d:Decision) WHERE NOT ()-[:OVERRIDES]->(d) "
        "RETURN d.id", {"cid": case_id}).result_set
    if not row:
        raise ValueError(f"case {case_id!r} has no uncorrected decision to override")
    old_id = row[-1][0]
    n = g.query("MATCH (d:Decision)<-[:OVERRIDES]-() RETURN count(d)").result_set[0][0] + 2
    ov_id = f"D-OV-{n:02d}"
    ts = datetime.now().isoformat(timespec="seconds")
    verdict = {"clear": "legit", "escalate": "unclear", "monitor": "legit"}.get(action, "unclear")
    g.query(
        """MATCH (c:Case {id:$cid}), (old:Decision {id:$oid}), (an:Analyst {id:$anid})
           CREATE (ov:Decision {id:$ovid, ts:$ts, verdict:$verdict, action:$action,
                     confidence:1.0, decided_by:'analyst', rationale:$reason,
                     policy_version:'v2.1'})-[:FOR_CASE {ts:$ts}]->(c)
           CREATE (ov)-[:OVERRIDES {reason:$reason, ts:$ts}]->(old)
           CREATE (ov)-[:MADE_BY {ts:$ts}]->(an)""",
        {"cid": case_id, "oid": old_id, "anid": analyst_id, "ovid": ov_id,
         "ts": ts, "verdict": verdict, "action": action, "reason": reason})
    journal("analyst", "override", case_id=case_id, override_id=ov_id,
            overruled=old_id, outcome=action, reason=reason)
    return {"override_id": ov_id, "overruled": old_id, "action": action}