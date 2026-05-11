"""Node functions for the LangGraph workflow.

Each function is small, testable, and returns a partial state update.
No input state mutation — all updates are via returned dicts.
"""

from __future__ import annotations

import re

from .state import AgentState, ApprovalDecision, Route, make_event

# ---------------------------------------------------------------------------
# Keyword sets for classification (priority order matters)
# ---------------------------------------------------------------------------
RISKY_KEYWORDS = {"refund", "delete", "send", "cancel", "remove", "revoke"}
TOOL_KEYWORDS = {"status", "order", "lookup", "check", "track", "find", "search"}
VAGUE_PRONOUNS = {"it", "this", "that"}
ERROR_KEYWORDS = {"timeout", "fail", "failure", "error", "crash", "unavailable"}


def _clean_words(text: str) -> list[str]:
    """Split text into lowercase words with punctuation stripped."""
    return [w.strip("?!.,;:'\"()[]{}") for w in text.lower().split()]


def intake_node(state: AgentState) -> dict:
    """Normalize raw query: strip whitespace, basic PII stub check, log intake."""
    query = state.get("query", "").strip()
    # PII stub: mask email-like patterns
    sanitized = re.sub(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "[EMAIL_REDACTED]", query)
    return {
        "query": sanitized,
        "messages": [f"intake: received query ({len(sanitized)} chars)"],
        "events": [make_event("intake", "completed", "query normalized and sanitized")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using priority-ordered keyword heuristics.

    Priority (highest first):
    1. risky  — refund, delete, send, cancel, remove, revoke
    2. tool   — status, order, lookup, check, track, find, search
    3. missing_info — short/vague queries with pronouns (it, this, that)
    4. error  — timeout, fail, failure, error, crash, unavailable
    5. simple — default fallback
    """
    query_lower = state.get("query", "").lower()
    clean = _clean_words(query_lower)
    route = Route.SIMPLE
    risk_level = "low"

    # Priority 1: Risky actions (highest priority)
    if any(kw in clean for kw in RISKY_KEYWORDS):
        route = Route.RISKY
        risk_level = "high"
    # Priority 2: Tool usage
    elif any(kw in clean for kw in TOOL_KEYWORDS):
        route = Route.TOOL
        risk_level = "low"
    # Priority 3: Missing information (vague short queries)
    elif len(clean) < 5 and any(p in clean for p in VAGUE_PRONOUNS):
        route = Route.MISSING_INFO
        risk_level = "low"
    # Priority 4: Error/failure detection
    elif any(kw in clean for kw in ERROR_KEYWORDS):
        route = Route.ERROR
        risk_level = "medium"
    # Priority 5: Simple (default)

    return {
        "route": route.value,
        "risk_level": risk_level,
        "messages": [f"classify: route={route.value}, risk={risk_level}"],
        "events": [make_event("classify", "completed", f"route={route.value}", risk_level=risk_level)],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    Generates a contextual clarification question based on the vague query.
    """
    query = state.get("query", "")
    question = (
        f"Your request \"{query}\" is too vague for me to help accurately. "
        "Could you please provide more details such as an order ID, "
        "account number, or a more specific description of what you need?"
    )
    return {
        "pending_question": question,
        "final_answer": question,
        "messages": [f"clarify: asked for more details about '{query}'"],
        "events": [make_event("clarify", "completed", "missing information requested")],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool with idempotent execution.

    Simulates transient failures for error-route scenarios to test retry loops.
    Non-error routes always succeed on first call.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get("scenario_id", "unknown")
    route = state.get("route", "")

    # Simulate transient failures for error-route scenarios
    if route == Route.ERROR.value and attempt < 2:
        result = f"ERROR: transient failure on attempt {attempt} for scenario {scenario_id}"
    else:
        query = state.get("query", "")
        result = f"tool-result: Successfully processed request for scenario={scenario_id} query='{query[:50]}'"

    return {
        "tool_results": [result],
        "messages": [f"tool: executed attempt={attempt}"],
        "events": [make_event("tool", "completed", f"tool executed attempt={attempt}", scenario_id=scenario_id)],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action with evidence and risk justification for approval."""
    query = state.get("query", "")
    risk_level = state.get("risk_level", "high")
    scenario_id = state.get("scenario_id", "unknown")

    proposed = (
        f"[RISKY ACTION] Scenario {scenario_id}: "
        f"Proposed action based on query '{query}'. "
        f"Risk level: {risk_level}. Requires human approval before execution."
    )
    return {
        "proposed_action": proposed,
        "messages": [f"risky_action: prepared action for approval (risk={risk_level})"],
        "events": [make_event("risky_action", "pending_approval", "approval required", risk_level=risk_level)],
    }


def approval_node(state: AgentState) -> dict:
    """Human-in-the-loop approval step with optional LangGraph interrupt().

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock approval so tests and CI run offline.
    Supports approve, reject, and edit decisions.
    """
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
            "scenario_id": state.get("scenario_id"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        # Mock approval for testing/CI
        decision = ApprovalDecision(
            approved=True,
            reviewer="mock-reviewer",
            comment=f"Auto-approved for scenario {state.get('scenario_id', 'unknown')}",
        )

    return {
        "approval": decision.model_dump(),
        "messages": [f"approval: approved={decision.approved} by {decision.reviewer}"],
        "events": [make_event("approval", "completed", f"approved={decision.approved}", reviewer=decision.reviewer)],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a bounded retry attempt with backoff metadata.

    Increments attempt counter. The routing function (route_after_retry)
    decides whether to continue retrying or escalate to dead_letter.
    """
    attempt = int(state.get("attempt", 0)) + 1
    max_attempts = int(state.get("max_attempts", 3))

    return {
        "attempt": attempt,
        "errors": [f"transient failure — retry attempt {attempt}/{max_attempts}"],
        "messages": [f"retry: attempt {attempt}/{max_attempts}"],
        "events": [make_event("retry", "completed", f"retry attempt {attempt}/{max_attempts}",
                              attempt=attempt, max_attempts=max_attempts)],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response grounded in tool_results and approval context."""
    tool_results = state.get("tool_results", [])
    approval = state.get("approval")
    route = state.get("route", "simple")

    if tool_results:
        latest_result = tool_results[-1]
        if approval:
            answer = f"[Approved] Action completed. Result: {latest_result}"
        else:
            answer = f"Based on the lookup, here is what I found: {latest_result}"
    elif route == "simple":
        query = state.get("query", "")
        answer = (
            f"Here is the answer to your question: '{query}' "
            "-- please follow the standard procedure in our help center."
        )
    else:
        answer = "Your request has been processed successfully."

    return {
        "final_answer": answer,
        "messages": [f"answer: generated response for route={route}"],
        "events": [make_event("answer", "completed", "answer generated", route=route)],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    Checks the latest tool result for ERROR markers. If found, signals retry.
    This is the key LangGraph advantage over LCEL — stateful retry loops.
    """
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""

    if "ERROR" in latest.upper():
        return {
            "evaluation_result": "needs_retry",
            "messages": ["evaluate: tool result indicates failure — retry needed"],
            "events": [make_event("evaluate", "completed", "tool result indicates failure, retry needed")],
        }
    return {
        "evaluation_result": "success",
        "messages": ["evaluate: tool result satisfactory"],
        "events": [make_event("evaluate", "completed", "tool result satisfactory")],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review.

    Final escalation in the error strategy: retry → fallback → dead letter.
    In production, this would persist to a dead-letter queue and alert on-call.
    """
    attempt = state.get("attempt", 0)
    scenario_id = state.get("scenario_id", "unknown")
    errors = state.get("errors", [])

    answer = (
        f"[DEAD LETTER] Scenario {scenario_id}: Request could not be completed "
        f"after {attempt} retry attempt(s). Error history: {len(errors)} errors logged. "
        f"Escalated for manual review."
    )
    return {
        "final_answer": answer,
        "messages": [f"dead_letter: max retries ({attempt}) exceeded for {scenario_id}"],
        "events": [make_event("dead_letter", "completed",
                              f"max retries exceeded, attempt={attempt}",
                              scenario_id=scenario_id, error_count=len(errors))],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    scenario_id = state.get("scenario_id", "unknown")
    route = state.get("route", "unknown")
    return {
        "messages": [f"finalize: workflow completed for {scenario_id} via route={route}"],
        "events": [make_event("finalize", "completed", "workflow finished",
                              scenario_id=scenario_id, route=route)],
    }
