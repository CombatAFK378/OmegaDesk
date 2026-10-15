"""R4 — Graph Tool Layer, v2 (v2.1 §9): 5 registered callables =
the §9 core-4 (get_case_context, find_precedents, trace_money_path,
find_shared_entities) + the whitelisted Cypher escape hatch.

The v1.3 13-tool surface and the write-tool stubs are GONE: Coordinator,
policy and execution are deterministic CODE (§5/§10) — see app/policy.py.
Import this package and everything registers."""
from .registry import TOOL_REGISTRY, Tool, run_tool
from . import read_tools  # noqa: F401  (side effect: registration)

__all__ = ["TOOL_REGISTRY", "Tool", "run_tool"]