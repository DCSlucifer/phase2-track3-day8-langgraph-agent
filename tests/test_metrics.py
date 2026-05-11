"""Tests for metrics module."""

from langgraph_agent_lab.metrics import metric_from_state, summarize_metrics


def test_metric_from_state():
    state = {
        "scenario_id": "S01",
        "route": "simple",
        "final_answer": "ok",
        "events": [],
        "errors": [],
    }
    metric = metric_from_state(state, "simple", False)
    assert metric.success is True
    assert metric.actual_route == "simple"


def test_summarize_metrics():
    state1 = {
        "scenario_id": "1", "route": "simple",
        "final_answer": "ok", "events": [], "errors": [],
    }
    state2 = {
        "scenario_id": "2", "route": "tool",
        "final_answer": None, "events": [], "errors": [],
    }
    m1 = metric_from_state(state1, "simple", False)
    m2 = metric_from_state(state2, "tool", False)
    report = summarize_metrics([m1, m2])
    assert report.total_scenarios == 2
    assert report.success_rate == 0.5
