"""Graph construction.

This module is intentionally import-safe. It imports LangGraph only inside the builder so unit tests
that check schema/metrics can run even if students are still debugging graph wiring.

Target architecture:
    START → intake → classify → [conditional routing]
      simple       → answer → finalize → END
      tool         → tool → evaluate → answer → finalize → END
      missing_info → clarify → finalize → END
      risky        → risky_action → approval → tool → evaluate → answer → finalize → END
      error        → retry → tool → evaluate → [retry loop or answer]
      max retry    → dead_letter → finalize → END
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .nodes import (
    answer_node,
    approval_node,
    ask_clarification_node,
    classify_node,
    dead_letter_node,
    evaluate_node,
    finalize_node,
    intake_node,
    retry_or_fallback_node,
    risky_action_node,
    tool_node,
)
from .routing import route_after_approval, route_after_classify, route_after_evaluate, route_after_retry
from .state import AgentState


def build_graph(checkpointer: Any | None = None):
    """Build and compile the LangGraph workflow.

    All paths terminate at finalize → END. The retry loop is bounded by max_attempts.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except Exception as exc:  # pragma: no cover - helpful install error
        raise RuntimeError("LangGraph is required. Run: pip install -e '.[dev]' or pip install langgraph") from exc

    graph = StateGraph(AgentState)

    # --- Register all nodes ---
    graph.add_node("intake", intake_node)
    graph.add_node("classify", classify_node)
    graph.add_node("answer", answer_node)
    graph.add_node("tool", tool_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("clarify", ask_clarification_node)
    graph.add_node("risky_action", risky_action_node)
    graph.add_node("approval", approval_node)
    graph.add_node("retry", retry_or_fallback_node)
    graph.add_node("dead_letter", dead_letter_node)
    graph.add_node("finalize", finalize_node)

    # --- Wire edges ---
    # Entry: START → intake → classify
    graph.add_edge(START, "intake")
    graph.add_edge("intake", "classify")

    # Conditional routing after classification
    graph.add_conditional_edges("classify", route_after_classify)

    # Tool path: tool → evaluate → [answer or retry]
    graph.add_edge("tool", "evaluate")
    graph.add_conditional_edges("evaluate", route_after_evaluate)

    # Missing info: clarify → finalize
    graph.add_edge("clarify", "finalize")

    # Risky path: risky_action → approval → [tool or clarify]
    graph.add_edge("risky_action", "approval")
    graph.add_conditional_edges("approval", route_after_approval)

    # Retry path: retry → [tool or dead_letter]
    graph.add_conditional_edges("retry", route_after_retry)

    # Terminal edges: answer/dead_letter → finalize → END
    graph.add_edge("answer", "finalize")
    graph.add_edge("dead_letter", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)


def export_mermaid(output_path: str | Path = "outputs/graph.mermaid") -> str:
    """Export the graph as a Mermaid diagram string and optionally save to file.

    Bonus extension: visual graph documentation.
    """
    graph = build_graph()
    mermaid_str = graph.get_graph().draw_mermaid()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mermaid_str, encoding="utf-8")
    return mermaid_str
