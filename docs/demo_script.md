# Demo script — OmegaDesk (3–4 min, §17 beats)

Record with the desk UI on `localhost:8000/app/` open beside FalkorDB Browser (`:3000`, graph
`desk`). Reset first (`python -m seed.seed` → 139/326). Keep Swagger at `:8000/docs` in a tab.

| # | beat (time) | on screen | what you say (gist) |
|---|---|---|---|
| 1 | Problem (15s) | UI header + alert list | "Single transactions look innocent. The decisions about them get forgotten the moment they're filed. This desk remembers." |
| 2 | Case C (40s) | Swagger `POST /sim/inject/C` → UI: pick new alert ▸ Investigate | Merchant fan-in fires. The agent reads signals, probes the money, and — because the KYC merchant has cleared precedents — escalates for review. |
| 3 | C override (the beat) | UI override form: AN-DEV ▸ clear ▸ reason | "The analyst disagrees — clears it with a reason. That reason lands in the graph as an OVERRIDES edge — a real Decision node." Show Browser: `queries/03_memory_lineage` override query. |
| 4 | Case C′ (40s) | Swagger inject `Cp` ▸ investigate | "A similar merchant a week later." It cites the clearance precedent (HOV-016) and C's fresh decision — **cleared again, with its own receipt.** Browser: the CITES path from the new Decision to the override. |
| 5 | Case D (30s) | inject `D` ▸ investigate | "Same fan-in shape, but no KYC behind it." The agent **distinguishes** the precedent (names BUSINESS_KYC absent) and freezes on evidence — memory couldn't be blindly copied. |
| 6 | Case E (20s) | (terminal) probe or UI | "The overruled decision HD-019 is gone from the desk's options — it is never cited; the correction cites itself." |
| 7 | Proof (30s) | UI footer ▸ 📊 benchmark | The with/without table: two decisions changed by memory (B and E), every miss reported. "Turn the memory off and the desk freezes a business it shouldn't." |
| 7b | The written record (25s) | on any open case: 📄 write the case report ▸ ⬇ download | "And the whole case reads as a citable document — every line tagged to its source. This is what a supervisor receives." Show the [1]-style tags. |
| 7c | Live world (10s) | ▶ make alerts stream live | "The desk isn't a replay — it watches live money while it remembers." Ticks climb on their own. |
| 8 | Limits (15s) | README §Limits | Planted synthetic world; one-model design; illustrative benchmark. |

**Cutaways if time allows:** scenario A's ring lighting up in the Browser; B's
device-probe-comes-back-empty pivot (visible in `journal.jsonl`).
Never cut beats 2-7 to make room.