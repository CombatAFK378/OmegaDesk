"""C4 — the cited case report (§16 C4): ONE LLM call, fully sourced.

Input = everything stored on the case (decision, citations, receipts, evidence,
signals) — read-only facts. Output = a plain-language report where every claim
carries its source in brackets: [decision D-…, evidence q…] — the Track-03
"sourcing" promise: not vibes, a bibliography.
Stored as a Report node (+ REPORTS edge) → the UI + /cases/{id} serve it.
"""
import json
from datetime import datetime

from .config import LLM_BASE_URL, LLM_MODEL
from .graph import get_graph
from .investigator import _client as invest_client
from .journal import journal


def build_report(case_id, facts, client=None):
    """One LLM call: the case's facts (from case_detail) → a sourced report.
    `facts` comes from the CALLER (the API's case_detail) — no import cycle."""
    client = client or invest_client()
    if not facts["decisions"]:
        raise ValueError("the case has no decision to report on yet — investigate first")

    decision = facts["decisions"][-1]
    lines = [
        "Write the desk's case report. PLAIN LANGUAGE for a compliance supervisor — nobody",
        "technical should have to decode it. Never use the internal code-words (PASS_THROUGH,",
        "FAN_IN, SHARED_DEVICE, SUB_THRESHOLD, KYC and the like); describe them in everyday",
        "words instead, e.g. 'money arrives and leaves almost straight away' instead of",
        "PASS_THROUGH, 'many people paying one account' instead of FAN_IN.",
        "Rules: ≤180 words; every factual claim must end with its source in square brackets",
        "using the SOURCES list I give you; if a claim has no listed source, don't make it.",
        "",
        "SOURCES:",
        f"[1] decision {decision['decision_id']} — action {decision['action']} at "
        f"{round((decision['confidence'] or 0) * 100)}% by {decision['decided_by']}",
        f"[2] the case's measured signals: " + "; ".join(
            f"{s['code']}={s['value']}" for s in facts["signals"]) or "(none)",
        f"[3] receipt {'present (digest ' + decision['receipt']['digest'][:12] + ')' if decision.get('receipt') else 'not issued'}",
        f"[4] the agent's own written reasoning (its rationale, quote-worthy)",
        f"[5] citations it made: " + "; ".join(
            f"{c['decision_id']} {'applies' if c['applies'] else 'distinguished'}"
            + (f" ({', '.join(c['distinguishing'])})" if c["distinguishing"] else "")
            for c in decision["cites"]) or "(none)",
        f"[6] evidence rows: " + "; ".join(
            f"{e['tool']} ({e['query_id']})" for e in facts["evidence"]) or "(none)",
        f"[7] freeze orders: " + "; ".join(f['order'] for f in facts["freeze_orders"]) or "(none)",
        "",
        f"CASE: {case_id} · alert {facts['alert'][0]['id'] if facts['alert'] else 'none'} "
        f"({facts['alert'][0]['type'] if facts['alert'] else '—'}) · target {facts['alert'][0]['target'] if facts['alert'] else '—'}",
        f"DECISION: {decision['action']} · verdict {decision['verdict']} · "
        f"{round((decision['confidence'] or 0) * 100)}% sure",
        f"AGENT'S RATIONALE: {decision['rationale'][:900]}",
        "",
        "Answer ONLY with the report body (no headings, no preamble).",
    ]
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": "\n".join(lines)}],
        temperature=0, max_tokens=2600)   # reasoning models think FIRST — give the answer room
    text = (resp.choices[0].message.content or "").strip()
    if not text:
        raise RuntimeError("empty report from the model")

    # the sources block rides OUTSIDE the model'd text (deterministic — can't be faked)
    sources = ["[1] decision " + decision["decision_id"],
               "[2] measured signals on the case"] + \
              [f"[5] citation {c['decision_id']}" for c in decision["cites"]] + \
              [f"[6] evidence {e['query_id']} ({e['tool']})" for e in facts["evidence"]] + \
              ([f"[3] receipt digest {decision['receipt']['digest']}"] if decision.get("receipt") else [])

    g = get_graph()
    g.query("MATCH (r:Report)-[:REPORTS]->(:Case {id:$cid}) DETACH DELETE r",
            {"cid": case_id})
    g.query(
        """MATCH (c:Case {id:$cid})
           CREATE (r:Report {id: 'RPT-' + $cid, ts:$ts, model:$model,
                     body:$body})-[:REPORTS {ts:$ts}]->(c)""",
        {"cid": case_id, "ts": datetime.now().isoformat(timespec="seconds"),
         "model": LLM_MODEL, "body": text})
    journal("reports", "built", case_id=case_id, model=LLM_MODEL,
            tokens={"in": resp.usage.prompt_tokens if resp.usage else 0,
                    "out": resp.usage.completion_tokens if resp.usage else 0})
    return {"case_id": case_id, "report": text, "sources": sources,
            "model": LLM_MODEL,
            "tokens": {"in": resp.usage.prompt_tokens if resp.usage else 0,
                       "out": resp.usage.completion_tokens if resp.usage else 0}}