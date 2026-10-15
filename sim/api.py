"""Phase 2 — HTTP control for the simulator (architecture §3: start/stop/inject)."""
from fastapi import APIRouter, HTTPException

from sim.generator import inject_scenario_a, inject_scenario_b, inject_scenario_c
from sim.simulator import sim_status, start_noise, stop_noise
from app.monitor import scan_once

router = APIRouter(prefix="/sim", tags=["simulator"])

INJECTORS = {"A": inject_scenario_a, "B": inject_scenario_b, "C": inject_scenario_c}


@router.get("/status")
async def status():
    return sim_status()


@router.post("/start")
async def start(interval: float = 2.0):
    return start_noise(interval)  # called on the event loop → create_task works


@router.post("/stop")
async def stop():
    return stop_noise()


@router.post("/inject/{scenario}")
async def inject(scenario: str):
    fn = INJECTORS.get(scenario.upper())
    if fn is None:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario!r} — use A/B/C")
    res = {"scenario": scenario.upper(), **fn()}
    res["monitor_scan"] = scan_once()  # stream: injected events get watched immediately
    return res