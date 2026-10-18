"""Phase 2 — HTTP control for the simulator (architecture §3: start/stop/inject)."""
from fastapi import APIRouter, HTTPException

from sim.generator import inject_scenario_a, inject_scenario_b, inject_scenario_c
from sim.injectors_c1 import inject_scenario_c_prime, inject_scenario_d, inject_scenario_e
from sim.simulator import sim_status, start_noise, stop_noise
from app.graph import get_graph
from app.monitor import scan_once
from seed.seed import seed_graph

router = APIRouter(prefix="/sim", tags=["simulator"])

INJECTORS = {"A": inject_scenario_a, "B": inject_scenario_b, "C": inject_scenario_c,
             "CP": inject_scenario_c_prime, "D": inject_scenario_d, "E": inject_scenario_e}


@router.get("/status")
async def status():
    return sim_status()


@router.post("/start")
async def start(interval: float = 2.0):
    return start_noise(interval)  # called on the event loop → create_task works


@router.post("/stop")
async def stop():
    return stop_noise()


@router.post("/reseed")
async def reseed():
    """Fresh demo world: stop the noise, wipe + replant the seed baseline —
    resets the sim clock (newest transaction) so the demo stories fire in-window."""
    stop_noise()
    seed_graph()
    return {"status": "fresh world planted", **sim_status()}


# injectors CREATE (not MERGE), so planting a story twice duplicates its accounts and
# every query then counts each payer N times — refuse a replant instead
PLANTED_MARKER = {"A": "A-EXIT", "B": "A-BT", "C": "A-C01", "CP": "A-CP01",
                  "D": "A-DARK-MER", "E": "A-E1"}


@router.post("/inject/{scenario}")
async def inject(scenario: str):
    fn = INJECTORS.get(scenario.upper())
    if fn is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario!r} — use A/B/C")
    marker = PLANTED_MARKER.get(scenario.upper())
    if marker and get_graph().query("MATCH (a:Account {id:$id}) RETURN count(a)",
                                    {"id": marker}).result_set[0][0]:
        raise HTTPException(status_code=409, detail=f"story {scenario.upper()} is already planted "
                                                    "— Reset to a fresh world to plant it again")
    res = {"scenario": scenario.upper(), **fn()}
    res["monitor_scan"] = scan_once()  # stream: injected events get watched immediately
    return res