"""Routing functions for conditional edges.

Each function takes the current state and returns the name of the next node.
These are used with graph.add_conditional_edges() to create dynamic routing.
"""

from __future__ import annotations

from .state import AgentState, Route


def route_after_classify(state: AgentState) -> str:
    """Map classified route to the next graph node.

    Handles all 5 route types with a safe default fallback to 'answer'.
    Unknown routes go to simple/answer path to prevent graph deadlocks.
    """
    route = state.get("route", Route.SIMPLE.value)
    mapping = {
        Route.SIMPLE.value: "answer",
        Route.TOOL.value: "tool",
        Route.MISSING_INFO.value: "clarify",
        Route.RISKY.value: "risky_action",
        Route.ERROR.value: "retry",
    }
    return mapping.get(route, "answer")


def route_after_retry(state: AgentState) -> str:
    """Decide whether to retry or escalate to dead-letter.

    Bounded retry: if attempt >= max_attempts, escalate to dead_letter.
    Otherwise, send back to tool for another attempt.
    """
    if int(state.get("attempt", 0)) >= int(state.get("max_attempts", 3)):
        return "dead_letter"
    return "tool"


def route_after_evaluate(state: AgentState) -> str:
    """Decide whether tool result is satisfactory or needs retry.

    This is the 'done?' check that creates the retry loop —
    a key LangGraph advantage over linear LCEL chains.
    """
    if state.get("evaluation_result") == "needs_retry":
        return "retry"
    return "answer"


def route_after_approval(state: AgentState) -> str:
    """Continue to tool if approved, redirect to clarify if rejected.

    Supports the reject path: if approval is denied, the user gets
    asked for clarification instead of executing the risky action.
    """
    approval = state.get("approval") or {}
    return "tool" if approval.get("approved") else "clarify"
