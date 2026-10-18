"""C1 — the Investigator (v2.1 §9): the ONLY LLM loop in the product.

Hand-rolled OpenAI-compatible tool loop → Groq gpt-oss-120b. The LLM chooses
which questions to ask (tool calls go through run_tool = authority + journal);
the graph answers. Its output is structured JSON only:
  {"verdict": fraud|legit|unclear, "confidence": 0..1,
   "evidence": [query_id], "precedents": [{decision_id, applies, distinguishing_signals}],
   "rationale": ≤120 words}
"""
import json
import re
import time

from openai import (APIConnectionError, APITimeoutError, InternalServerError,
                    OpenAI, RateLimitError)

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL
from .journal import journal
from .tools import TOOL_REGISTRY, run_tool

TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "get_case_context",
        "description": "Everything known about the case: scope accounts + holder KYC, "
                       "computed signals, the triggering alert, recent transactions, "
                       "existing decisions. Call this first.",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "string", "description": "the case id"}},
            "required": ["case_id"]}}},
    {"type": "function", "function": {
        "name": "find_precedents",
        "description": "Past decisions on cases sharing signals with this one, ranked "
                       "by signal overlap + entity proximity. Overruled decisions are "
                       "excluded. For each precedent you must judge: applies, or is it "
                       "distinguishable (name the differing signals)?",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "string"},
            "limit": {"type": "integer", "description": "max precedents, default 3"}},
            "required": ["case_id"]}}},
    {"type": "function", "function": {
        "name": "trace_money_path",
        "description": "Follow the money: SENT→Transaction→TO chains between two accounts, "
                       "with per-leg amounts. REQUIRED: src (the originating account id) and "
                       "dst (the destination account id). Use it to show the money's route.",
        "parameters": {"type": "object", "properties": {
            "src": {"type": "string"}, "dst": {"type": "string"},
            "max_hops": {"type": "integer", "description": "≤6"},
            "as_of": {"type": "string", "description": "replay as of a past moment"}}}}},
    {"type": "function", "function": {
        "name": "find_shared_entities",
        "description": "Overlap among suspect accounts: shared devices, identity links, "
                       "shared counterparties, shared merchants.",
        "parameters": {"type": "object", "properties": {
            "account_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["account_ids"]}}},
    {"type": "function", "function": {
        "name": "prove_absence",
        "description": "Run the negative checklist on this case: shared devices with "
                       "frozen accounts, identity links, payments to frozen accounts, "
                       "structuring among payers, velocity, unverified payers. ALL passing "
                       "= a RECEIPT proving the flagged shape is benign (e.g. payroll into "
                       "a verified merchant) — the desk's only honest path to 'clear'.",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "string", "description": "the case id"}}}}},
    {"type": "function", "function": {
        "name": "hub_centrality",
        "description": "Betweenness centrality on the money paths around this case: "
                       "which account is the funnel's heart. Use it to point at the "
                       "pattern's operator.",
        "parameters": {"type": "object", "properties": {
            "case_id": {"type": "string"},
            "k": {"type": "integer", "description": "neighborhood hop expansion, ≤2"}}}}},
]
# gpt-oss (harmony) wants a structured-answer channel — give it an official one;
# without it the model improvises a tool named "JSON" and the API 400s.
VERDICT_TOOL = "respond"
TOOLS_SCHEMA.append({"type": "function", "function": {
    "name": VERDICT_TOOL,
    "description": "Submit your final verdict. Call this instead of writing prose.",
    "parameters": {"type": "object", "properties": {
        "verdict": {"type": "string", "enum": ["fraud", "legit", "unclear"]},
        "confidence": {"type": "number"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "precedents": {"type": "array", "items": {"type": "object", "properties": {
            "decision_id": {"type": "string"}, "applies": {"type": "boolean"},
            "distinguishing_signals": {"type": "array", "items": {"type": "string"}}},
            "required": ["decision_id", "applies"]}},
        "rationale": {"type": "string"}},
        "required": ["verdict", "confidence", "rationale"]}}})

SYSTEM_PROMPT = """You are the Investigator on an AML compliance desk. The graph is the
evidence room; you are the detective. Decide whether the alerted pattern is fraud, and whether
the desk's past decisions apply to this case.

Method:
1. Call get_case_context first — read the signals and scope.
2. Probe the strongest hypothesis with the read tools (money path, shared entities). If the
   device/identity hypothesis comes back empty, BRANCH to money-shape evidence.
3. Call find_precedents. For each candidate:
   - Shares 2+ signals and no polarity flip → DEFAULT applies=true.
   - Say applies=false ONLY naming a signal present on one side, absent on the other
     (e.g. BUSINESS_KYC). A different past verdict alone is NOT distinguishing.
   - ALWAYS list every precedent you reasoned about (applies true AND false); if a similar
     case's decision was CORRECTED (overruled), include its correction id too.
4. If the shape looks like a legitimate business pattern (verified business receiver, regular
   billing schedule, fresh unrelated payers), CALL prove_absence before concluding: a passing
   receipt is the desk's ONLY honest path to 'clear' (verdict legit).
5. When done, CALL THE respond TOOL with the verdict object (never plain prose):
   {"verdict": "fraud|legit|unclear", "confidence": 0.0-1.0, "evidence": ["q1"],
    "precedents": [{"decision_id": "...", "applies": true|false, "distinguishing_signals": [...]}],
    "rationale": "<=120 words"}

Confidence anchors (fixed):
- fraud-grade → 0.85+: SHARED_DEVICE or RING_MEMBER with a frozen linked account in scope,
  OR a clean money-shape (≥80% pass-through, structured drips), OR a threshold-avoidance
  fan-in: >5 distinct senders, each with amounts ≥0.75× the reporting threshold, in one
  window. A business-KYC badge on the receiver does NOT explain a threshold-hugging
  payment pattern by itself — structuring-grade remains fraud-grade; ONLY an APPLICABLE
  PRECEDENT from the desk's own history (cited) de-escalates it.
- CORRECTED TWIN RULE: if a same-signal case's decision was overruled/corrected AND you have
  NOT proven a signal-level distinction — a catalog signal code present on one side, absent
  on the other — cap confidence ≤0.80 and escalate (human review), naming the correction id
  in precedents. Review, don't confidently freeze the twin of a corrected case.
  If you DO prove the distinction, name the differing code in distinguishing_signals and
  decide on the evidence alone (anchors above apply)."""

MAX_STEPS = 8
RESPOND_ONLY = [t for t in TOOLS_SCHEMA if t["function"]["name"] == VERDICT_TOOL]
FINAL_NUDGE = (f"Investigation budget used. Call the {VERDICT_TOOL} tool now with your "
               "verdict object, based on the evidence you already have.")
JSON_FALLBACK = re.compile(r"\{.*\}", re.DOTALL)


def _client():
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY missing in ~/omegadesk/.env — C1 needs it")
    # SDK default is a 600s timeout × 2 retries: one stalled cloud request froze a case for
    # minutes. 60s per call is ~5× a normal step; _call's backoff loop retries the timeout.
    return OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY, timeout=60, max_retries=1)


def _schema_args(tc):
    try:
        return json.loads(tc.function.arguments or "{}")
    except json.JSONDecodeError:
        return {}


def _parse_verdict(text):
    """Parse the final JSON out of the model's text; tolerant of fences/prose."""
    if not text:
        return None
    m = JSON_FALLBACK.search(text)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    verdict = d.get("verdict")
    if verdict not in ("fraud", "legit", "unclear"):
        return None
    try:   # code compares confidence against the policy thresholds — keep it a 0..1 number
        d["confidence"] = min(max(float(d.get("confidence") or 0.0), 0.0), 1.0)
    except (TypeError, ValueError):
        d["confidence"] = 0.0
    d.setdefault("evidence", [])
    d.setdefault("precedents", [])
    d.setdefault("rationale", "")
    return d


def investigate_case(case_id, client=None):
    """One investigation: the LLM tool loop → structured verdict + the run's
    telemetry (tool sequence + tokens) for the journal."""
    client = client or _client()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Investigate case {case_id}. Start with its context."},
    ]
    calls, seq, tokens_in, tokens_out = [], [], 0, 0
    final_verdict = None
    seen = {}   # (tool, args) → query_id of the first answer

    def _as_verdict(args):
        d = _parse_verdict(json.dumps(args)) if isinstance(args, dict) else None
        return d

    def _call(client, messages, tools=TOOLS_SCHEMA):
        """One chat call with 429 backoff + truncation guard (reasoning models
        spend output tokens thinking before they answer)."""
        delay = 15
        resp = None
        for attempt in range(7):
            try:
                resp = client.chat.completions.create(
                    model=LLM_MODEL, messages=messages, tools=tools,
                    tool_choice="auto", temperature=0, max_tokens=3000)
                msg = resp.choices[0].message
                truncated = (getattr(resp.choices[0], "finish_reason", None) == "length"
                             and not msg.tool_calls and not (msg.content or "").strip())
                if not truncated or attempt >= 5:
                    return resp
                messages.append({"role": "assistant", "content": ""})
                messages.append({"role": "user", "content":
                                 "Continue — call the respond tool with your verdict now."})
            except (RateLimitError, InternalServerError, APIConnectionError,
                    APITimeoutError) as exc:   # quota + cloud-transient → retry, not crash
                if attempt >= 5:
                    raise
                time.sleep(min(delay, 30))
                delay = min(delay * 2, 90)
        return resp

    # the last step offers ONLY the respond tool: the model must answer, it can't
    # keep reading until the budget runs out (that ended runs as "unclear 0.0")
    for step in range(MAX_STEPS + 1):
        last = step == MAX_STEPS
        if last:
            messages.append({"role": "user", "content": FINAL_NUDGE})
        resp = _call(client, messages, tools=RESPOND_ONLY if last else TOOLS_SCHEMA)
        usage = getattr(resp, "usage", None)
        if usage:
            tokens_in += usage.prompt_tokens or 0
            tokens_out += usage.completion_tokens or 0
        msg = resp.choices[0].message
        if not msg.tool_calls:
            final_verdict = _parse_verdict(msg.content)
            if final_verdict or last:
                break
            # prose without a verdict → ask for the structured answer, keep going
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({"role": "user", "content": FINAL_NUDGE})
            continue
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [{"id": tc.id, "type": "function",
                                         "function": {"name": tc.function.name,
                                                      "arguments": tc.function.arguments}}
                                        for tc in msg.tool_calls]})
        # every tool call gets a tool reply — an unanswered call makes the next request invalid
        for tc in msg.tool_calls:
            args = _schema_args(tc)
            if tc.function.name == VERDICT_TOOL or tc.function.name not in TOOL_REGISTRY:
                # the respond tool (or an improvised tool holding the verdict) = final answer
                dv = _as_verdict(args)
                if dv and not final_verdict:
                    final_verdict = dv
                note = ("verdict recorded" if dv else
                        f"not a valid verdict: call {VERDICT_TOOL} with verdict "
                        "fraud|legit|unclear, confidence 0-1 and a rationale")
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps({"tool": tc.function.name,
                                                        "note": note})})
                continue
            if final_verdict:   # verdict already in hand — don't run reads after it
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps({"skipped": True})})
                continue
            key = (tc.function.name, json.dumps(args, sort_keys=True, default=str))
            if key in seen:   # same read, same args → point back instead of re-sending the payload
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps({"tool": tc.function.name,
                                                        "note": f"already answered as {seen[key]} "
                                                                "above — reuse it and move on"})})
                continue
            try:
                result = run_tool(tc.function.name, "investigator", **args)
                payload = {"query_id": f"q{len(calls) + 1}", "tool": tc.function.name,
                           "args": args, "result": result, "error": None}
                seq.append(tc.function.name)
            except (PermissionError, KeyError, ValueError, TypeError) as exc:
                payload = {"query_id": f"q{len(calls) + 1}", "tool": tc.function.name,
                           "args": args, "result": None, "error": str(exc)[:200]}
            calls.append(payload)
            if payload["error"] is None:
                seen[key] = payload["query_id"]
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(payload, default=str)[:1600]})
        if final_verdict:
            break

    verdict = final_verdict or {
        "verdict": "unclear", "confidence": 0.0, "evidence": [],
        "precedents": [], "rationale": "investigator could not produce a structured verdict"}

    journal("investigator", "llm_run", case_id=case_id, tokens={"in": tokens_in, "out": tokens_out},
            tool_sequence=seq, verdict=verdict["verdict"], confidence=verdict.get("confidence"),
            rationale=verdict.get("rationale", ""))
    total = tokens_in + tokens_out
    if total > 2500:
        time.sleep(20)  # token-pace: stay under groq's 8k TPM for the runner
    return {**verdict, "tool_sequence": seq, "tokens": {"in": tokens_in, "out": tokens_out},
            "calls": calls}