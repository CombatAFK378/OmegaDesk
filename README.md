# OmegaDesk

An AML investigation desk for a synthetic fintech. A graph is the evidence room *and* the
institutional memory: a monitor flags fraud **shapes**, an agent investigates using read-only
tools, past decisions and analyst corrections act as precedent, and every verdict is a
first-class graph node with a replayable evidence chain.

> **One-line pitch:** a fraud desk that learns from its analysts' corrections. Precedents live in
> the graph, overruled precedents are never cited again, and a with/without benchmark proves the
> graph changed the decision.

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

Environment (`~/omegadesk/.env`) — never commit it:

```
FALKORDB_PORT=6380
GRAPH_NAME=desk
LLM_API_KEY=<your key>
LLM_BASE_URL=https://api.groq.com/openai/v1     # or https://ollama.com/v1
LLM_MODEL=openai/gpt-oss-120b                   # ollama: gpt-oss:120b
```

## Run the demo path (§17 in three minutes)

```bash
python -m seed.seed                  # clean world
curl -X POST localhost:8000/sim/inject/C    # merchant fan-in → alert     (Swagger: POST /sim/inject/C)
# UI: pick the new alert ▸ Investigate ▸ read the decision
# UI: record an override (AN-DEV ▸ clear ▸ reason)   ← this becomes precedent
curl -X POST localhost:8000/sim/inject/Cp   # a SIMILAR merchant later
# UI: investigate C′ ▸ it cites the clearance precedent (HOV-016-family) → escalate, not freeze
```

The with/without proof — the benchmark (§12):

```bash
python scripts/c1_exit_test.py       # 12 LLM investigations; writes benchmark_report.json
```

Then **📊 with/without benchmark** in the UI footer shows the pre-registered table, per-case
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

## Where the "AI" is (disclosure per event rules 12–13)

- **One LLM loop, exactly:** `app/investigator.py` (the Investigator). It chooses the read
  tools, judges precedents, and returns a structured verdict — never an action. Model:
  OpenAI-compatible `gpt-oss-120b` (Groq or Ollama Cloud); the design is provider-agnostic.
- What the model sees: the case's scope/signals through the four read tools plus ranked
  precedents. It never sees your code, filesystem, or anything outside the planted graph.
- **Everything else is deterministic:** signals (`app/signals.py`), monitoring (`app/monitor.py`),
  policy and actions (`app/policy.py`), scoping (`app/coordinator.py`). Code has authority;
  the model has an opinion.
- This repository's code was written in pair-programming with AI coding agents (Claude Code /
  OpenAI-compatible CLIs) in Oct 2026 — per event rule 13, disclosed here. Concept, graph model,
  and the precedent thesis are the team's (see the Rule-8 note below).

## Pre-event note (Rule 8)

The event's coding window opened **Oct 15, 00:01 IST**. Before that: concept notes, the graph
model sketch and Docker/installer setup only (this repo's Phase-0 skeleton + seed were built
as environment-level work then; the v2.1 rebuild — transaction-node model, decision memory,
precedent tools, benchmark — started Oct 15 with the coding window). **This README's setup was
written to be followed from a fresh clone.**

## Testing

| command | what |
|---|---|
| `python scripts/phase1_exit_test.py` … `phase4` | seeds + asserts exact graph counts, sim, monitor, tool layer, policy |
| `python scripts/c1_exit_test.py` | the Investigator: with/without benchmark + §16 exit items (needs the LLM key) |
| `python scripts/c2_exit_test.py` | the desk API + served UI + fresh-clone consistency (no LLM spend) |

Test counts are exact asserts, never "looks about right."

## Notes

- FalkorDB binds host **6380** (compose maps `6380:6379`) so it never collides with a local
  Redis on 6379.
- `journal.jsonl` is the desk's audit log (who called what, when, why) — read it live:
  `tail -f journal.jsonl`.
- Known limits (§18): planted synthetic world; the LLM is the only heuristic; benchmark is
  illustrative, not statistical.