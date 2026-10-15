"""Phase 2 — background noise loop: the world ticking in real time.

Start/stop/status are controlled over HTTP (sim/api). The loop uses the same
deterministic emitter as scripted runs; only its rng seed is time-based, so
live noise varies while scripted replays stay identical.
"""
import asyncio
import random
import time

from app.graph import get_graph
from sim.generator import noise_tick
from app.monitor import scan_once

_task = None
_running = False
_ticks = 0
_interval = 2.0


async def _loop(interval, rng_seed):
    global _ticks
    rng = random.Random(rng_seed)
    g = get_graph()
    i = 0
    while True:
        noise_tick(g, rng, i)
        scan_once(g)  # stream watch: the world writes, the monitor scans (§3)
        i += 1
        _ticks = i
        await asyncio.sleep(interval)


def start_noise(interval=2.0):
    """Must be called from an async route (needs a running event loop)."""
    global _task, _running, _ticks, _interval
    if _running:
        return sim_status()
    _interval = interval
    _ticks = 0
    _running = True
    _task = asyncio.create_task(_loop(interval, int(time.time()) % 100000))
    return sim_status()


def stop_noise():
    global _task, _running
    if _task is not None:
        _task.cancel()
        _task = None
    _running = False
    return sim_status()


def sim_status():
    return {"running": _running, "ticks": _ticks, "interval_sec": _interval}