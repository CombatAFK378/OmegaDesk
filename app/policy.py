"""R4 — Policy engine (v2.1 §10): DETERMINISTIC action decisions — code, not a model.

The Investigator (LLM) proposes a verdict + confidence; this file decides the
action. Everything with authority is code (§4 pillar 3). The Executor (C1)
calls decide_action + override_action and journals every decision it writes.
"""
FREEZE_MIN = 0.85
ESCALATE_MIN = 0.60

ACTIONS = ("freeze", "escalate", "monitor", "clear")


def decide_action(confidence, has_mitigating=False, has_aggravating=True,
                  absence_proven=False):
    """§10 table:
    - clear only with proof-of-absence + mitigating + zero aggravating
    - ≥0.85 → freeze, UNLESS a mitigating precedent applies → escalate
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


ALLOWED_OVERRIDE_ACTIONS = {"escalate"}


def override_action(base_action, reason):
    """§10 override safety rule: an analyst override can ONLY move an action
    toward human review. It can never auto-clear, and it never auto-freezes.
    Returns 'escalate'; raises on a missing reason or an unknown action."""
    if not str(reason or "").strip():
        raise ValueError("an override without a written reason is not recorded (§10)")
    if base_action not in ACTIONS:
        raise ValueError(f"unknown action {base_action!r}")
    return "escalate"