# OmegaDesk

An AML investigation desk for a synthetic fintech. A graph is the evidence room *and* the
institutional memory: a monitor flags fraud **shapes**, an agent investigates using read-only
tools, past decisions and analyst corrections act as precedent, and every verdict is a
first-class graph node with a replayable evidence chain.

> **One-line pitch:** a fraud desk that learns from its analysts' corrections. Precedents live in
> the graph, overruled precedents are never cited again, and a with/without benchmark proves the
> graph changed the decision.

## Submission — Graph Hacks (WeMakeDevs × FalkorDB)

| | |
|---|---|
| **Tracks entered** | **01 Agents That Act on Connected Data** (primary) · 02 Agent Memory and Coordination · 03 Company Brain |
| **Demo video** | TODO: add link (YouTube unlisted / public Drive) |
| **Deployment** | local setup — full instructions below (fresh clone → working desk in ~5 min) |
| **Graph model** | [The graph model](#the-graph-model-v21-6) below |
| **Cypher queries** | [`queries/`](queries/) + inline in `app/` (signals, tools, proof-of-absence) |
| **Benchmark result** | [`benchmark_report.json`](benchmark_report.json) — committed, also shown in the UI footer |
| **AI-use disclosure** | [Where the "AI" is](#where-the-ai-is-disclosure-per-event-rules-1113) |

---

## Setup — fresh clone to working desk

Prereqs: **Docker**, **Python 3.11+**, one OpenAI-compatible LLM key (Groq free tier or an
[Ollama](https://ollama.com) cloud key both work).

```bash
git clone https://github.com/CombatAFK378/OmegaDesk.git
cd OmegaDesk

cp .env.example .env          # then fill LLM_API_KEY (and LLM_BASE_URL/LLM_MODEL)
docker compose up -d          # FalkorDB (graph) on :6380 + FalkorDB Browser on :3000

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python -m seed.seed           # rebuild the deterministic world (139 nodes / 326 edges / 25 alerts)
uvicorn app.main:app --port 8000
```

Then open:

| URL | what |
|---|---|
| `http://localhost:8000/app/` | **the desk UI** — alerts → investigate → decision, citations, evidence, override |
| `http://localhost:8000/docs` | Swagger for every endpoint (incl. the LLM ones) |
| `http://localhost:3000` | FalkorDB Browser — host `host.docker.internal`, port `6380`, graph `desk` |

Environment (`.env` in the repo root, copied from `.env.example`) — never commit it:

```
FALKORDB_PORT=6380
GRAPH_NAME=desk
LLM_API_KEY=<your key>
LLM_BASE_URL=https://api.groq.com/openai/v1     # or https://ollama.com/v1
LLM_MODEL=openai/gpt-oss-120b                   # ollama: gpt-oss:120b
```

## C3 — Track 01 strength (built)

| capability | what it does |
|---|---|
| **Proof-of-absence** (`app/tools/absence.py`) | the desk's only honest path to `clear`: a 9-point negative checklist (devices, identity, frozen counterparties, structuring, velocity, unverified payers, pass-through shape) run by **code**; an all-clean pass issues a replayable **receipt** (digest + as_of) stored on the Decision, and the case auto-clears — no human wait for obviously-benign shapes |
| **Analyst routing** (`app/routing.py`) | escalated/frozen cases land on a named queue deterministically: device-rings → `AN-PRIYA`, merchant shapes → `AN-DEV`; shown in the UI |
| **Hub centrality** (`app/tools/graph_algos.py`) | FalkorDB's built-in **`algo.betweenness`** on the money graph (Account + Transaction, SENT/TO), ranked over the case's neighborhood — points at the pass-through hub (e.g. the mule in the middle of a chain); for a pure fan-in, where no account passes money through, it names the drain instead and says so. A read tool the agent can call (also via MCP); query in [`queries/05_hub_betweenness.cypher`](queries/05_hub_betweenness.cypher) |
| **MCP server** (`app/mcp_server.py`) | the desk exposed over the Model Context Protocol — an external MCP client can run a **full investigation**; wire it into Claude Desktop with `docs/claude_desktop_config.json`:

```bash
.venv/bin/python -m app.mcp_server      # stdio transport; the C3 exit test drives it with a real MCP client
```

## Track 02 — agent memory (what persists, and where)

| memory | how it lives in the graph |
|---|---|
| **Episodic** — every investigation | one `Decision` node per run, with its `EVIDENCE` (query, snapshot, as-of) — replayable |
| **Lessons** — analyst corrections | an override `Decision` that `OVERRIDES` the wrong one; later cases `CITES {applies, distinguishing}` it |
| **Procedural** — the rule applied | each decision `APPLIED_POLICY` → the `Regulation` it applied |
| **Memory that updates** | an overruled decision is dropped from precedent search and refused at citation time — never cited again |
| **Persists across sessions** | the graph lives in a Docker volume: restart the app and every case, lesson and citation is still there |
| **Shared between agents** | the MCP server hands the same memory to any MCP client (`past_similar_cases`, `investigate_alert`) — an outside agent reads it and adds to it |
| **Proof it matters** | the with/without benchmark: memory changes the decision in B and E; the UI's **Without memory** switch reproduces it live |

## Run the demo path (all from the UI)

Open the desk → **🎬 Demo tools** → **Reset to a fresh world**, then plant the stories **in this
order**, investigating each before planting the next (the monitor watches the window before the
newest transaction):

| # | Demo tools button | then | expected |
|---|---|---|---|
| 1 | Plant the phone-sharing ring (A) | `A-EXIT` alert ▸ Investigate | freeze — cites `D-2025-0417`, the 2025 ring on the same device |
| 2 | Plant the clean funnel (B) | `A-BT` alert ▸ Investigate, again with **Without memory** | escalate with memory, freeze without — the AI's confidence decides, so this one varies between runs |
| 3 | Plant the verified business (C) | `A-MER-PAY` alert ▸ Investigate | clear — the proof-of-absence receipt |
| 4 | Plant the trap (E) | investigates itself; click again with **Without memory** on | escalate citing the correction `HOV-019` · freeze without |
| 5 | Plant its look-alike (C′) | the same `A-MER-PAY` alert ▸ Investigate again | clear — cites C's fresh decision and `HOV-016` |
| 6 | Plant the dark look-alike (D) | `A-DARK-MER` alert ▸ Investigate | freeze — distinguishes every clearance (no business KYC) |

Then correct any decision in the **Human override** panel — the corrected decision is never cited
again. Each story plants once per world (a replant is refused; Reset to start over). The same steps
over HTTP: `POST /sim/reseed`, `POST /sim/inject/{A|B|C|E|CP|D}`, `POST /cases/investigate`.

The with/without proof — the benchmark (§12):

```bash
python scripts/c1_exit_test.py       # 12 LLM investigations; writes benchmark_report.json
```

Then **📊 with/without benchmark** in the UI footer shows the expected-vs-actual table, per-case
tokens, the decisions memory changed, and every miss.

## The graph model (v2.1, §6)

World: `Person → OWNS → Account → SENT → Transaction → TO → Account` (money is nodes, not text),
`Device` (`USED_DEVICE`), `Merchant` (`OPERATED_BY`, `business_kyc`).

Desk: `Alert` (detector output), `Case` (`FOR_ALERT`, `ABOUT` = scope), `Signal` (`EXHIBITS`,
value/as-of), `Decision` (`FOR_CASE`; `CITES {applies, distinguishing}` precedents;
`OVERRIDES` the corrected decision; `APPLIED_POLICY`), `FreezeOrder` (`FREEZES`, `ISSUED_BY`),
and `EVIDENCE {query_id, snapshot, as_of}` — every claim the agent made, replayable.
Account status is *derived* from `FreezeOrder` events; nothing is mutated in place.

Handy queries live in [`queries/`](queries/) — graph overview, the §7 fraud patterns, the
memory lineage (citations + overrides), evidence replay.

## Where the "AI" is (disclosure per event rules 11–13)

- **One LLM loop, exactly:** `app/investigator.py` (the Investigator). It chooses the read
  tools, judges precedents, and returns a structured verdict — never an action. Model:
  OpenAI-compatible `gpt-oss-120b` (Groq or Ollama Cloud); the design is provider-agnostic.
- What the model sees: the case's scope/signals through the four read tools plus ranked
  precedents. It never sees your code, filesystem, or anything outside the planted graph.
- **Everything else is deterministic:** signals (`app/signals.py`), monitoring (`app/monitor.py`),
  policy and actions (`app/policy.py`), scoping (`app/coordinator.py`). Code has authority;
  the model has an opinion.
- This repository's code was written in pair-programming with AI coding agents (Claude Code /
  OpenAI-compatible CLIs) in Oct 2026 — per event rule 11, disclosed here. Concept, graph model,
  and the precedent thesis are the team's (see the Rule-8 note below).

## Pre-event note (Rule 8)

The event's coding window opened **Oct 15, 00:01 IST**. Stated plainly, so judges can check it
against the git history:

- **Before the window:** concept notes and a graph-model sketch (not in this repo), plus two
  commits on **Oct 14** (`bdcf2e4`, `e442973`): the environment skeleton — Docker compose for
  FalkorDB, `.env` config, the graph connection, a `/health` endpoint — and a first seed with
  its exit test.
- **What survives from them:** ~280 of ~7,100 lines (≈4%), mostly config/connection code and
  parts of `seed/` and the Phase 0/1 tests (`git blame` shows exactly which).
- **Everything that makes the product** — the Transaction-node model, signals, decision memory and
  precedents, the Investigator, policy engine, proof-of-absence, benchmark, MCP server, UI — was
  built from **Oct 15** onward, in the commits that follow.

**This README's setup was written to be followed from a fresh clone.**

## Testing

| command | what |
|---|---|
| `python scripts/phase1_exit_test.py` … `phase4` | seeds + asserts exact graph counts, sim, monitor, tool layer, policy |
| `python scripts/c1_exit_test.py` | the Investigator: with/without benchmark + §16 exit items (needs the LLM key) |
| `python scripts/c2_exit_test.py` | the desk API + served UI + fresh-clone consistency (no LLM spend) |

Test counts are exact asserts, never "looks about right."

## Notes

- `§` numbers in this README and the code refer to sections of the team's internal design doc,
  which is not published; everything they describe is implemented and tested here.
- FalkorDB binds host **6380** (compose maps `6380:6379`) so it never collides with a local
  Redis on 6379.
- `journal.jsonl` is the desk's audit log (who called what, when, why) — read it live:
  `tail -f journal.jsonl`.
- Known limits (§18): planted synthetic world; the LLM is the only heuristic; benchmark is
  illustrative, not statistical.
- **AI disclosure (hackathon rule 11):** built with disclosed AI coding assistance throughout
  the hackathon; every design decision, benchmark result, and technical claim was driven and
  verified by the team, which can explain all of it.