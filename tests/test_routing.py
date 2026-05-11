from langgraph_agent_lab.routing import (
    route_after_classify,
    route_after_evaluate,
    route_after_retry,
)
from langgraph_agent_lab.state import Route


def test_route_simple():
    assert route_after_classify({"route": Route.SIMPLE.value}) == "answer"


def test_route_risky():
    assert route_after_classify({"route": Route.RISKY.value}) == "risky_action"


def test_route_after_evaluate_success():
    assert route_after_evaluate({"evaluation_result": "success"}) == "answer"


def test_route_after_retry():
    assert route_after_retry({"attempt": 3, "max_attempts": 3}) == "dead_letter"
