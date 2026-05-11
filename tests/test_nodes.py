"""Unit tests for individual node functions."""

from langgraph_agent_lab.nodes import (
    answer_node,
    classify_node,
    dead_letter_node,
    evaluate_node,
    finalize_node,
    intake_node,
    retry_or_fallback_node,
)
from langgraph_agent_lab.state import Route


class TestClassifyNode:
    """Test priority-ordered keyword classification."""

    def test_simple_route(self):
        result = classify_node({"query": "How do I reset my password?"})
        assert result["route"] == Route.SIMPLE.value

    def test_tool_route_status(self):
        result = classify_node({"query": "Please lookup order status for 12345"})
        assert result["route"] == Route.TOOL.value

    def test_tool_route_track(self):
        result = classify_node({"query": "Track my shipment #789"})
        assert result["route"] == Route.TOOL.value

    def test_tool_route_search(self):
        result = classify_node({"query": "Search for product availability"})
        assert result["route"] == Route.TOOL.value

    def test_missing_info_it(self):
        result = classify_node({"query": "Can you fix it?"})
        assert result["route"] == Route.MISSING_INFO.value

    def test_missing_info_this(self):
        result = classify_node({"query": "Help me with this"})
        assert result["route"] == Route.MISSING_INFO.value

    def test_risky_refund(self):
        result = classify_node({"query": "Refund this customer"})
        assert result["route"] == Route.RISKY.value

    def test_risky_delete(self):
        result = classify_node({"query": "Delete customer account"})
        assert result["route"] == Route.RISKY.value

    def test_risky_cancel(self):
        result = classify_node({"query": "Cancel my subscription immediately"})
        assert result["route"] == Route.RISKY.value

    def test_risky_remove(self):
        result = classify_node({"query": "Remove my payment method from the system"})
        assert result["route"] == Route.RISKY.value

    def test_risky_revoke(self):
        result = classify_node({"query": "Revoke API access for user admin"})
        assert result["route"] == Route.RISKY.value

    def test_risky_send(self):
        result = classify_node({"query": "Send confirmation email to customer"})
        assert result["route"] == Route.RISKY.value

    def test_error_timeout(self):
        result = classify_node({"query": "Timeout failure while processing request"})
        assert result["route"] == Route.ERROR.value

    def test_error_crash(self):
        result = classify_node({"query": "Application crash on startup"})
        assert result["route"] == Route.ERROR.value

    def test_risky_priority_over_tool(self):
        """Risky keywords should take precedence over tool keywords."""
        result = classify_node({"query": "Delete and check order status"})
        assert result["route"] == Route.RISKY.value

    def test_default_simple(self):
        result = classify_node({"query": "What are your business hours?"})
        assert result["route"] == Route.SIMPLE.value

    def test_empty_query_defaults_simple(self):
        result = classify_node({"query": ""})
        assert result["route"] == Route.SIMPLE.value


class TestEvaluateNode:
    def test_success_result(self):
        result = evaluate_node({"tool_results": ["mock-tool-result for scenario=S01"]})
        assert result["evaluation_result"] == "success"

    def test_error_result(self):
        result = evaluate_node({"tool_results": ["ERROR: transient failure attempt=0"]})
        assert result["evaluation_result"] == "needs_retry"

    def test_empty_results(self):
        result = evaluate_node({"tool_results": []})
        assert result["evaluation_result"] == "success"


class TestDeadLetterNode:
    def test_produces_final_answer(self):
        result = dead_letter_node({
            "attempt": 3, "scenario_id": "S07", "errors": ["e1", "e2", "e3"],
        })
        assert result["final_answer"] is not None
        assert "DEAD LETTER" in result["final_answer"]


class TestIntakeNode:
    def test_strips_whitespace(self):
        result = intake_node({"query": "  hello world  "})
        assert result["query"] == "hello world"

    def test_pii_masking(self):
        result = intake_node({"query": "Contact me at user@example.com"})
        assert "[EMAIL_REDACTED]" in result["query"]
        assert "user@example.com" not in result["query"]


class TestAnswerNode:
    def test_with_tool_results(self):
        result = answer_node({"tool_results": ["result-1"], "route": "tool"})
        assert "result-1" in result["final_answer"]

    def test_simple_route(self):
        result = answer_node({
            "tool_results": [], "route": "simple", "query": "How to reset?",
        })
        assert result["final_answer"] is not None


class TestRetryNode:
    def test_increments_attempt(self):
        result = retry_or_fallback_node({"attempt": 0, "max_attempts": 3})
        assert result["attempt"] == 1

    def test_records_error(self):
        result = retry_or_fallback_node({"attempt": 1, "max_attempts": 3})
        assert len(result["errors"]) == 1


class TestFinalizeNode:
    def test_emits_event(self):
        result = finalize_node({"scenario_id": "S01", "route": "simple"})
        assert len(result["events"]) == 1
        assert result["events"][0]["node"] == "finalize"
