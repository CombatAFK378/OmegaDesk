# OmegaDesk — the compliance war-room: agents that see fraud shapes on a graph, act on them, and never forget a case (architecture.md).

> Full README ships in Phase 9 (§16). This is the dev quickstart until then.

## Quickstart

```bash
docker compose up -d                              # FalkorDB on :6379
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # paste Groq key
uvicorn app.main:app --reload                     # API on :8000
```

## Layout

| Dir | Holds | Phase |
|---|---|---|
| `app/` | FastAPI service, graph connection, config | 0 → |
| `sim/` | Event simulator ("the world") | 2 |
| `seed/` | Graph schema + seed script | 1 |
| `ui/` | Desk UI (React, 4 panes) | 7 |
| `scripts/` | Phase exit tests | — |

## Phase 0 exit tests

```bash
.venv/bin/python scripts/phase0_roundtrip.py write   # create probe + CONFIG dir
.venv/bin/python scripts/phase0_roundtrip.py read    # exact round-trip
docker compose down && docker compose up -d          # restart
.venv/bin/python scripts/phase0_roundtrip.py read    # data survives = volume works
.venv/bin/python scripts/phase0_roundtrip.py clean
```