# OmegaDesk — Architecture v1.1
_Graph Hacks (WeMakeDevs × FalkorDB) • Oct 15–18, 2026 • written Oct 13, 2026_

**Changelog v1.1:** agent framework removed entirely — plain FastAPI service with hand-rolled tool-calling loops (no ADK, no LangChain glue). Desk UI = React, 4 panes, Streamlit fallback. Model-swap = base_url + env change only.
**Changelog v1.2:** development is **phase-wise, not date-wise** (§12 + §17) — every phase ends with a concrete exit test that must be green before the next phase starts.

> **How to use this file (future coding session):** read top to bottom, build in the order of §17 (phases + exit tests). Everything here is decided — start Phase 0 without re-deciding anything.
>
> **Timing legality (event rule 8):** main coding and design work begins **no earlier than Oct 15, 00:01 IST**. Before that: environment setup (Docker, keys, repo skeleton, installs) and reading this file only.

---

## 1. What this product is

**OmegaDesk** — the compliance war-room for a synthetic fintech: a team of AI agents that investigates suspected money-laundering patterns on a shared graph, **proves each verdict with query evidence**, **acts** (freeze, case, report, assignment), and **remembers every case forever** in the graph itself.

- **Who it serves:** the AML compliance desk of a trading company (SEBI-style context — regulatory freezes and reporting must be justified with auditable proof).
- **What problem it kills:** individual transactions look innocent; the crime lives in *relationships* (fan-in funnels, shared devices, coordinated timing). Rules engines can't see shapes, vector RAG can't see connections, raw LLMs hallucinate paths. The graph is the only honest evidence room.
- **One-line pitch:** "Fraud is a shape, not a number. OmegaDesk is the desk that sees shapes, acts on them, and never forgets a case."

**Stack at a glance:** FastAPI (everything server-side) · hand-rolled agent loops (OpenAI-compatible client, no framework) · FalkorDB via Docker/Cloud · `falkordb` python client · React desk UI (4 panes) · FalkorDB Browser (graph viz, zero build) · Groq free-tier gpt-oss-120b primary / Ollama glm-5.3-flash as benchmark-gated fallback. Zero paid APIs.

## 2. Design pillars (every decision defers to these)

1. **The graph is the evidence room; the LLM is the detective.** The LLM decides *which* questions to ask; FalkorDB answers deterministically. The LLM never reads raw bulk transaction data.
2. **Every verdict is replayable.** Each point in an agent's rationale maps to a stored query + result (Evidence edges). Auditability beats cleverness.
3. **Memory IS the graph.** No chat logs, no vector store, no embeddings. Cross-session recall = one traversal. (Embeddings consciously excluded — see §9.)
4. **Agents act with authority, gated by confidence.** High → act; medium → human approval; low → monitor. Never claim certainty.
5. **Zero paid APIs.** Free tiers for the build; Ollama credits only as the quality reserve.
6. **No framework bloat.** The graph + tool contracts ARE the architecture. Four loops, not framework objects.
7. **FalkorDB is load-bearing by construction:** remove it → no multi-hop detection, no ring clustering, no case lineage. The product collapses. (Submission rule 3: passed.)

## 3. System overview — components

```
[Event Simulator] → [FalkorDB Graph] ← [Rules Monitor] → [Alert]
                            ↑                                ↓
                    [Graph Tool Layer]              [Coordinator (loop)]
                            ↑                                ↓
                   [Desk React UI]              [Investigator (loop)]
                            ↑                                ↓
                      [Human approval]  ←──  [Compliance Checker] → [Executor (loop)]
                                                             ↓
                                              [actions: freeze / case / report / assign]
                                                    (all outcomes → graph)
```

| Component | Responsibility | Type |
|---|---|---|
| **Event Simulator** ("the world") | Generates synthetic fintech activity: account opens, logins (device fingerprints), transfers, payouts. Runs scenario scripts (planted fraud + realistic noise). Writes every event into the graph as it emits. HTTP control: start/stop, inject scenario | FastAPI module |
| **Rules Monitor** (dumb tier, non-AI) | Simple threshold logic on the stream: fan-in bursts, sub-threshold daily repetition, velocity spikes. Emits **Alert nodes** only. Deliberately dumb — it is the trigger, not the detector | FastAPI module |
| **Graph (FalkorDB)** | Single source of truth: entities, events, cases, policy, people, all memory | Docker (dev) / FalkorDB Cloud (demo) |
| **Agent runtime** | The desk's staff (§5) — **hand-rolled tool-calling loops in plain Python** (OpenAI-compatible client → Groq/Ollama). Four loops, one typed tool registry, no agent framework | FastAPI service |
| **Graph Tool Layer** | The only way agents touch the graph: named tools (§6), each with purpose, input, output, read/write class. Python functions + one typed registry over the `falkordb` client (self-owned; **not** the official read-only `FalkorDB-mcp` — we need controlled *write* authority; official MCP server noted as optional add-on) | FastAPI service |
| **Desk UI** | Alert queue • Case view (verdict, confidence, evidence list, action log) • Human approval lane • link-out to FalkorDB Browser for the graph money-shot. **React, max 4 panes** (Streamlit = fallback if not standing by day-3 morning) | React + Vite, served by FastAPI |
| **Regulation layer** | Regulation nodes (modelled SEBI-style AML clauses) linked to transaction patterns; every freeze/report cites its source node | Part of graph + compliance loop |

## 4. Graph data model (the heart)

All in one graph, `desk`. (Multigraph not needed — Track 2 memory = case lineage, not per-user walls.)

**Nodes** (properties described functionally):

| Node | Key properties |
|---|---|
| `Person` | name, kyc_status |
| `Account` | id, opened_at, type (customer/merchant), status (active/frozen) |
| `Device` | fingerprint id (shared use links accounts) |
| `Employer/Merchant` | business KYC flag, registered cadence (false-positive guard) |
| `Alert` | id, type (fan_in / sub_threshold_repeat / velocity), window, created_at, status |
| `Case` | id, verdict, confidence, status (open/closed/escalated), created_at, outcome |
| `Regulation` | id, title, clause text summary (e.g. "structuring below reporting threshold §5") |
| `Analyst` | name, team (risk/AML), on_call_today, skills |

**Edges** (properties shown where they carry meaning):

| Edge | Meaning / properties |
|---|---|
| `SENT` account → account | the money flow: amount, timestamp. Chained SENT = money path (walk with variable-length patterns) |
| `USED_DEVICE` account → device | timestamp (same-device chains are ring evidence) |
| `SAME_IDENTITY` account ↔ account | shared email/nominee/address discovered at KYC time |
| `PAID_BY` account → employer | employment link (false-positive guard) |
| `TRIGGERED` alert ← events summary link | which activity raised it |
| `INVESTIGATED` case → alert | case provenance |
| `EVIDENCE` case → node/edge reference | each finding, with query id + result snapshot as properties |
| `VERDICT` / `RESOLVED_AS` case → outcome node | decision text + date + deciding agent |
| `CITED_BY` case → regulation | policy citations |
| `ASSIGNED_TO` case → analyst | routing |
| `FROZEN_BY` account ← case | freeze order provenance, timestamp, order |

**Sizing note:** dataset stays small (hundreds of accounts, low thousands of edges — comfortably ≤ a few MB, far under the 100MB cloud cap).

## 5. Agent roster (one model, four roles — roles differ by prompt + tools, not by model)

| Loop | Job | Tools it may call |
|---|---|---|
| **Coordinator (Desk Lead)** | Receives new Alerts; triages severity; dispatches Investigator; tracks the case to closure | case tools (read), dispatch |
| **Investigator** (the detective) | Plans the investigation step by step; runs graph tools; builds the evidence chain; outputs verdict + confidence + evidence list | all read tools |
| **Compliance Checker** | Verifies the pattern against Regulation nodes; confirms authority (can we freeze?); **false-positive veto** (e.g. payroll); cites policy | read tools + policy/citation tools |
| **Executor** | Performs actions: freeze accounts, create/close Case, link evidence, assign analyst, draft the escalation report (citations pulled from graph) | write tools |

**Coordination pattern:** agents hand work to each other **through the graph** — the Case node is the shared blackboard; each loop appends findings/status as timestamped nodes/edges. Any agent's output is another's context. This is the Track-2 story, implemented, not claimed.

**Scope cut line (day-3 decision):** merge Executor's report drafting into it unless time clearly allows more. Four loops are enough to win.

## 6. Graph tool contracts (functional — implementation chooses exact Cypher)

Read tools (Investigator + Compliance):
1. `run_cypher_readonly` — bounded, whitelisted patterns (escape hatch for pattern queries; logged)
2. `get_entity_profile(entity_id)` — full 1-hop + key aggregates (volume, counterparties, devices)
3. `find_shared_signals(account_ids)` — device / identity / IP overlap matrix among suspects
4. `trace_money_path(src, dst, max_hops)` — walks SENT chains, returns path + amounts
5. `find_fan_in(target, window)` — many-to-one accumulation shape
6. `detect_communities(window)` — ring clustering (graph algorithm — the one thing rules/SQL/vector can't do)
7. `prior_cases(entity_id)` — **memory recall**: cases linked to this entity/device with outcomes
8. `cite_policy(pattern_type)` — matching Regulation nodes

Write tools (Executor only; every write journaled):
9. `create_case(alert_id)` / `update_case(case_id, findings, verdict, confidence)`
10. `link_evidence(case_id, node_refs, query_log)` — evidence chain
11. `freeze_account(account_id, case_id)` — status write + simulated notification side-effect
12. `assign_analyst(case_id, rule)` — on-call/team lookup
13. `draft_report(case_id)` — LLM text with citations pulled via CITED_BY

## 7. Investigation flow (the demo's backbone)

1. Simulator emits events → Monitor raises **Alert #N** (fan-in: ≥5 senders → 1 target in a tight window).
2. **Coordinator** opens a Case shell, dispatches **Investigator**.
3. **Investigator loop** (each step logged as Evidence):
   a. entity profiles of senders → weak alone
   b. shared signals → device/identity overlap (strong)
   c. fan-in shape + money path → the funnel visible
   d. `detect_communities` → "these accounts form one sealed cluster"
   e. `prior_cases` on overlapping device/entity → **institutional memory hit**
4. **Verdict:** confidence + rationale, every point mapped to a query result.
5. **Compliance Checker:** policy match (cite Regulation "structuring below threshold"), authority check, **false-positive veto path** (employer/KYC/cadence — if payroll, close as normal with reasoning; this beat is in the demo).
6. **Executor:** freeze (per confidence policy) → case finalized → analyst assigned → report drafted.
7. **All outcomes written back** → the desk is smarter for the next alert.
8. **Cold-restart moment:** kill the app, restart, run `prior_cases(device_fp)` → full lineage (case, verdict, analyst, cited policy). No chat memory. The graph remembered.

## 8. Confidence & action policy

| Confidence | Action |
|---|---|
| ≥ 0.85 + clean evidence chain | auto-freeze + full case |
| 0.60–0.85 | escalate to **human approval** queue (shown in UI) |
| < 0.60 | monitor only |

False-positive guards: employer nodes with business-KYC + monthly cadence; KYC-verified businesses; regular payroll patterns.

## 9. Planted scenarios + the one deliberate exclusion

| # | Scenario | Signals planted | Expected outcome |
|---|---|---|---|
| A | **Device ring** (layering) | 4-6 mule accounts, sub-threshold daily inflows, shared device fingerprint, nightly funnel to exit wallet, crypto exit | caught; high confidence; freeze + report |
| B | **Clean funnel** (no device overlap) | distinct devices/identities; fan-in + timing + IP overlap only | caught via money shape/timing — proves it's not a device-fingerprinting trick |
| C | **Payroll false positive** | 200 employees paid from one company wallet, monthly | NOT flagged (or initially suspicious → closed as legitimate with reasoning) — proves judgment, not pattern-matching |
| + | **Background noise** | thousands of boring legit events (salary credits, purchases, normal transfers) | keeps the demo honest; system must not cry wolf |

Sitting on `Device D1`'s memory lineage: an older closed case linked to the same device — feeds the Track-2 restart moment.

**Why NO embeddings (final):** (1) no fuzzy matching needed — synthetic world, clean IDs, deterministic properties; (2) the "similar cases" job is done by graph traversal, not similarity search; (3) a vector store inside the product would contradict the thesis ("structured graph memory beats vector memory"). README notes fuzzy entity resolution as future work. One line, done.

## 10. Model & infra config

**LLM decision (locked):**
- **Primary:** `gpt-oss-120b` via **Groq free tier** — dev + integration + demo-capable; $0. Native tool-calling over the OpenAI-compatible protocol.
- **Switch trigger:** after end-to-end build, run the 10 scripted cases as a benchmark. If verdict/tool-call quality < ~90% correct or tool-call formatting is flaky → switch to `glm-5.3-flash` via **Ollama Cloud** (existing credits) — one env swap (base_url + key), zero code change.
- **No agent framework.** Plain FastAPI service + hand-rolled tool-calling loops over the OpenAI-compatible client. Coordinator / Investigator / Compliance / Executor are four loop functions, not framework objects. Reason: full control, fewer moving parts, and a hand-built runtime is itself the explainability story.
- **One model, four agent prompts.** No embeddings, no vector DB, no fine-tuning, no second provider.
- Voice (gated, cut-ready, deadline **Oct 17 EOD**): Gemini Live (free tier) or the existing LiveKit/STT/TTS pipe. Garnish only; the text demo must stand alone.

**Infra:**
- **Dev:** FalkorDB in local Docker + FastAPI + Groq.
- **Live demo deployment:** FalkorDB Cloud free tier — **known constraints to design around:** no persistence, instances auto-stopped after 1 day idle (deleted after 7), 100MB cap. Therefore: keep dataset small; ship a **seed script that rebuilds the graph in under a minute** so a stale/dead instance is a non-event; record the video right after reseeding. **Complete local setup (`docker compose up` + seed + run) ships in the README regardless** — rules accept either, and local is unfailable.
**Deployment priority (user decision, final):** local Docker is the backbone and the demo machine. Live cloud deployment = **stretch goal only if day-4 time allows**; rules explicitly accept complete-local-setup-only submissions, so a missing cloud link loses nothing. The reseed script ships regardless (it's tiny and doubles as the local reset used by every phase test).
- **UI hosting:** Vite build served by the same FastAPI app (single origin, no CORS). Dev/test entirely local.

## 11. Track mapping & side prizes

| Track | How this build serves it |
|---|---|
| **1 — Agents That Act on Connected Data** | Investigator walks multi-hop paths + community detection → Executor freezes/accounts/files with the proving path shown live |
| **2 — Agent Memory & Coordination** | Graph-native memory (case lineage survives restarts) + agents coordinating through the shared case blackboard |
| **3 — Company Brain** | Regulation citations with source nodes, analyst routing, case history — "why did you freeze this?" answered from the desk's own graph |

Name **all three** at submission; README states them from line one.
**Blog post (AirPods prize):** draft on day 4 — working title: *"Our agents kept forgetting their cases, so we deleted vector memory."*
**Top-50 t-shirts:** achievable; submit early on day 4 (buffer).

## 12. Development plan — phase-wise

Development runs **phase by phase (§17) — no dated phases.** Each phase has a defined build and an **exit test that must be fully green before the next phase starts.** Natural pace over the 4-day event: Phases 0–4 ≈ day 1–2 · Phases 5–6 ≈ day 2–3 · Phases 7–8 ≈ day 3 · Phase 9 = day 4 with submission buffer. Voice gate remains Oct 17 EOD if attempted; the UI-phase fallback rule (§3) applies on schedule shock.
Standing rule: every core file touched by the user (must explain graph model, queries, architecture per event rules 12–13). AI assistance (Claude Code / Hermes) disclosed in README.

## 13. Demo video beats (3–4 min)

1. **The problem (15s):** 20,000 boring transactions scroll; voiceover: "the crime is in none of them."
2. **Alert fires (20s):** fan-in alert on screen → coordinator dispatches.
3. **Investigation (60–90s):** investigator's steps visible; evidence list grows; community detection shows the ring light up in FalkorDB Browser; memory hit on device D1's old case.
4. **Action (30s):** freeze + case + report citation from Regulation node; analyst assigned.
5. **The mic-drop (20s):** app killed, restarted cold → "prior cases on this device?" → full lineage in one query.
6. **Limitations (15s):** honest boundaries read-out (judges reward this).
Voice overlay inserted here if it passed the gate.

## 14. Known limits (README section, pre-written)

- Patternless single-shot fraud (no repeatable shape) — undetectable by design; out of scope for any system.
- Cold-start accounts (no history, no links) — early-signal only.
- Slow-wash (month-scale drip) — low confidence → routes to human review.
- Fuzzy entity resolution out of scope (deterministic IDs in the synthetic world); noted as future work.
- Positioning: **the desk's first responder and evidence builder** — triage + proof in seconds, humans sign the regulatory decision.

## 15. Judge Q&A one-liners

- *Why a graph?* "Fraud is a shape, not a number."
- *Why not vector RAG?* "Similarity can't answer 'show me the path of the money'; traversal can."
- *What breaks if FalkorDB is removed?* "Everything — device chains, ring clustering, case memory. It's the load-bearing wall."
- *Which LLM and why?* "One model, four prompts: gpt-oss-120b (open weights, $0, native tool-calling), benchmark-gated swap to glm-5.3-flash. Budget: zero paid APIs."
- *Why no agent framework?* "Four hand-rolled tool-calling loops and a typed tool registry. The graph + tool contracts ARE the architecture; a framework would be glue bloat."
- *Can it hallucinate a path?* "It can't — paths come from stored query results; the agent picks the questions, the graph produces the answers."

## 16. Submission checklist (from event rules — mapped)

- [ ] Public repo
- [ ] README: setup + graph data model + the Cypher queries the product depends on
- [ ] Demo video (beats in §13)
- [ ] Complete local setup (guaranteed path — fully rules-compliant on its own)
- [ ] *(Stretch, if time remains)* live deployment link (FalkorDB Cloud + reseed script)
- [ ] Tracks named (all three)
- [ ] AI use disclosed
- [ ] Own/understand every component (rules 12–13)

## 17. Development phases & exit tests

**Rules for this section:** one phase at a time; its exit test must be fully green before the next starts. Every phase test starts from a clean state (reset = rerun the seed script) — deterministic, no manual setup. Tests assert over counts, edges, and statuses in the graph, not "looks about right".

### Phase 0 — Environment & skeleton *(environment setup only — legal before the event)*
**Build:** FalkorDB Docker up (volume mounted) · repo skeleton (app / sim / seed / ui) · .env (Groq key; Ollama held as reserve) · FastAPI `/health`.
**Exit test:**
1. `/health` returns OK.
2. `falkordb` client connects; a create + match round-trip returns exactly what was written.
3. `docker compose down && up` → data survives (volume works).

### Phase 1 — Graph schema & seed script
**Build:** node/edge labels + indices per §4 · seed script: Regulation nodes (2–3 clauses), Analysts (2), Employer node (payroll), baseline normal accounts, and the **old closed case linked to Device D1** (the memory lineage the demo leans on).
**Exit test:**
1. Run seed → exact expected node/edge counts (asserted, not eyeballed).
2. FalkorDB Browser: old case visibly linked to D1.
3. Reset + rerun seed → identical counts (idempotent).

### Phase 2 — Event Simulator
**Build:** noise mode + scenario scripts A/B/C; every emitted event written to the graph; HTTP control (start/stop/inject).
**Exit test:**
1. Noise-only run for T ticks → counts grow as predicted.
2. Inject A → D1 device edges + funnel SENT edges present.
3. Same seed twice → identical counts (determinism).
4. Inject C → PAID_BY edges present, business-KYC flags set.

### Phase 3 — Rules Monitor (dumb tier)
**Build:** fan-in detector (≥5 senders → 1 target in window), sub-threshold repeat, velocity → Alert nodes only.
**Exit test:**
1. A injected → exactly one `fan_in` alert with TRIGGERED link.
2. C injected → **zero alerts** (false-positive guard holds at the monitor tier).
3. Noise-only for M ticks → zero alerts (no crying wolf).
4. Write journal shows the monitor creating only Alert nodes.

### Phase 4 — Graph Tool Layer (13 tools)
**Build:** typed registry per §6; all read tools live; write tools defined as stubs (unused until Phase 6); journaling on for every call.
**Exit test:**
1. Each read tool's output matches manual Browser inspection on the seeded graph (fan-in finds scenario A's wallet; `trace_money_path` returns the 2-hop chain with amounts; `prior_cases(D1)` returns the old case; `cite_policy` returns the structuring clause).
2. Whitelist rejects a non-approved Cypher pattern (security + sanity).

### Phase 5 — Investigator + Coordinator loops (read-only verdicts)
**Build:** the four prompts (Coordinator skeleton + full Investigator); investigator consumes read tools only; outputs verdict + confidence + evidence list; **no actions executed**.
**Exit test (10-case benchmark harness: A/B/C + noise variants):**
1. ≥ 9/10 verdicts correct.
2. Every verdict's evidence list is non-empty and each item is *replayable* — rerunning the stored query returns the stored snapshot.
3. C-type cases → suspicion stays in the "monitor" band or lower (not flagged).
4. Case completes in < 2 minutes on gpt-oss-120b (latency sane for the demo).

### Phase 6 — Compliance Checker + Executor (actions enabled)
**Build:** policy match + false-positive veto; write tools go live: freeze / case finalize / evidence links / analyst assign / report draft; full journaling.
**Exit test:**
1. A full run → accounts frozen (status + FROZEN_BY edges), case closed with CITED_BY + EVIDENCE edges, analyst assigned, report present with citation.
2. C full run → case closed as **legitimate**, zero freezes.
3. Kill the app, restart, query `prior_cases` on D1 → full lineage returned (**the Track-2 memory proof**).
4. Journal audit: every write attributable to Executor, nothing rogue.

### Phase 7 — Desk UI (React, 4 panes; Streamlit fallback if not standing by this phase's start per §3)
**Build:** alert queue · case view (verdict, confidence, evidence, action log) · approval lane · Browser link-out.
**Exit test (manual checklist):**
1. Alert appears live → open case → evidence renders with sources.
2. Approve a medium-confidence case → graph status updates and the log shows it.
3. Cold restart → prior cases visible.
4. Browser console: zero errors; dark, readable, no layout breaks (user standard: no sloppy visuals on camera).

### Phase 8 — Model benchmark & gate decision
**Build:** benchmark runner over the 10 scripted cases; model selected by env config.
**Exit test:**
1. gpt-oss-120b ≥ ~90% correct → keep as shipped model.
2. If below → env-swap to glm-5.3-flash, rerun, expect ≥ 9/10.
3. If BOTH fail → the prompts/tool descriptions are the bug, not the model — fix those before any further model change (this is the honest debugging order).

### Phase 9 — Ship
**Build:** README (setup, graph model, Cypher used, limits, AI disclosure) · demo video (§13) · blog draft · reseed/local-reset script · *(stretch, only if time: FalkorDB Cloud live link)* · submit early.
**Exit test:**
1. Fresh clone → following **only** the README: `docker compose up` + seed + run works end-to-end.
2. *(If stretch live link was attempted)* Cloud reseed completes in under 60 seconds; otherwise skip — §16's guaranteed path is local-only.
3. Video covers all §13 beats; every screen readable.
4. §16 checklist fully ticked.

---
*Architecture ends. This file is the contract — build phase-wise, test-gate everything.*