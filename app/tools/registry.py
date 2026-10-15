"""Phase 4 — typed tool registry (architecture §6).

The ONLY way agents (Phase 5) touch the graph. `run_tool(name, actor_role)`
is the single dispatch path: authority check → call → journal. Every call is
journaled, including authority rejections — the audit story starts here.
No framework: a dataclass, a dict, one function.
"""
import os
from dataclasses import dataclass
from typing import Callable, Dict

from ..journal import journal

# Agent roles (Phase 5) and the tool kinds they may call (§5/§6)
READ_ROLES = {"coordinator", "investigator", "compliance"}
WRITE_ROLES = {"executor"}

# v1.3 ablation → v2.1 §12 with/without benchmark: prove precedents CHANGE decisions.
# export MEMORY_ABLATION=on before uvicorn (or set_memory_ablation() in code) to strip
# precedent recall for a run; C1's benchmark runs each case with this off and on.
_MEMORY_TOOLS = {"find_precedents"}
MEMORY_ABLATION = os.getenv("MEMORY_ABLATION", "off").strip().lower() == "on"


def set_memory_ablation(on):
    global MEMORY_ABLATION
    MEMORY_ABLATION = bool(on)
    return {"memory_ablation": "on" if MEMORY_ABLATION else "off"}


@dataclass(frozen=True)
class Tool:
    name: str
    fn: Callable
    kind: str        # "read" | "write"
    purpose: str     # doubled as the LLM's tool description in Phase 5
    params: Dict[str, str]


TOOL_REGISTRY: Dict[str, Tool] = {}


def register(kind, purpose, params):
    def deco(fn):
        tool = Tool(name=fn.__name__, fn=fn, kind=kind, purpose=purpose, params=params)
        TOOL_REGISTRY[tool.name] = tool
        return fn
    return deco


def run_tool(name, actor_role, **kwargs):
    """Single dispatch: authority → call → journal. Rejections journaled too."""
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        raise KeyError(f"unknown tool {name!r} — registered: {sorted(TOOL_REGISTRY)}")
    allowed = READ_ROLES if tool.kind == "read" else WRITE_ROLES
    if actor_role not in allowed:
        journal("tool_layer", "authority_rejected",
                tool=name, role=actor_role, allowed=sorted(allowed))
        raise PermissionError(
            f"role {actor_role!r} may not call {tool.kind} tool {name!r} (allowed: {sorted(allowed)})")
    if MEMORY_ABLATION and name in _MEMORY_TOOLS:
        journal("tool_layer", "memory_ablated", tool=name, role=actor_role,
                note="v2.1 §12: precedent recall stripped for this run")
        return {"ablated": True, "precedents": [], "case_id": kwargs.get("case_id")}
    try:
        result = tool.fn(**kwargs)
    except NotImplementedError:
        journal(actor_role, "tool_stub_call", tool=name,
                params=str(kwargs)[:200], note="write tool goes live in Phase 6")
        raise
    except PermissionError as e:
        journal("tool_layer", "whitelist_rejected", tool=name, role=actor_role,
                detail=str(e)[:200])  # §6: the hatch is logged, rejections included
        raise
    journal(actor_role, "tool_call", tool=name, kind=tool.kind,
            params=str(kwargs)[:200], result=str(result)[:400])
    return result