import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("langgraph") is None,
    reason="langgraph not installed in local environment",
)

from langgraph_agent_lab.graph import build_graph  # noqa: E402
from langgraph_agent_lab.persistence import build_checkpointer  # noqa: E402
from langgraph_agent_lab.state import Route, Scenario, initial_state  # noqa: E402


@pytest.mark.parametrize(
    ("query", "expected_route"),
    [
        ("How do I reset my password?", Route.SIMPLE.value),
        ("Please lookup order status for order 123", Route.TOOL.value),
        ("Refund this customer", Route.RISKY.value),
        ("Can you fix it?", Route.MISSING_INFO.value),
        ("Timeout failure while processing request", Route.ERROR.value),
        ("What are your business hours?", Route.SIMPLE.value),
        ("Track my shipment #789", Route.TOOL.value),
        ("Cancel my subscription immediately", Route.RISKY.value),
        ("Help me with this", Route.MISSING_INFO.value),
        ("Application crash on startup", Route.ERROR.value),
        ("Remove my payment method from the system", Route.RISKY.value),
        ("Search for product availability", Route.TOOL.value),
        ("Revoke API access for user admin", Route.RISKY.value),
    ],
)
def test_graph_runs_all_routes(query, expected_route):
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="smoke", query=query, expected_route=Route(expected_route),
    )
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}
    result = graph.invoke(state, config=config)
    assert result["route"] == expected_route
    assert result.get("final_answer") or result.get("pending_question")


def test_dead_letter_route():
    """S07: max_attempts=1 should exhaust retries and hit dead_letter."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="dead_letter_test",
        query="System failure cannot recover after multiple attempts",
        expected_route=Route.ERROR,
        max_attempts=1,
    )
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}
    result = graph.invoke(state, config=config)
    assert result["route"] == Route.ERROR.value
    assert result.get("final_answer") is not None
    answer = result["final_answer"].lower()
    assert "dead letter" in answer or "could not be completed" in answer


def test_risky_route_has_approval():
    """Risky scenarios should produce an approval decision."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    scenario = Scenario(
        id="risky_test",
        query="Delete customer account",
        expected_route=Route.RISKY,
        requires_approval=True,
    )
    state = initial_state(scenario)
    config = {"configurable": {"thread_id": state["thread_id"]}}
    result = graph.invoke(state, config=config)
    assert result["route"] == Route.RISKY.value
    assert result.get("approval") is not None
    assert result["approval"]["approved"] is True


def test_all_routes_terminate():
    """Every route should reach finalize node."""
    graph = build_graph(checkpointer=build_checkpointer("memory"))
    cases = [
        (Route.SIMPLE.value, "How do I reset my password?"),
        (Route.TOOL.value, "Lookup order status for 123"),
        (Route.MISSING_INFO.value, "Can you fix it?"),
        (Route.RISKY.value, "Refund this customer"),
        (Route.ERROR.value, "Timeout failure processing"),
    ]
    for route_value, query in cases:
        scenario = Scenario(
            id=f"term_{route_value}",
            query=query,
            expected_route=Route(route_value),
        )
        state = initial_state(scenario)
        config = {"configurable": {"thread_id": state["thread_id"]}}
        result = graph.invoke(state, config=config)
        events = result.get("events", [])
        finalize_events = [e for e in events if e.get("node") == "finalize"]
        assert len(finalize_events) > 0, f"Route {route_value} did not reach finalize"
