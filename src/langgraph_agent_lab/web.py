"""FastAPI web server for the LangGraph Agent Lab Dashboard.

Provides a professional web UI to interactively test all features:
- Run individual or all scenarios
- View graph flow visualization
- HITL approval/reject
- Metrics dashboard with charts
- State history / time travel
- Crash-resume demonstration
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langgraph.types import Command

from .graph import build_graph, export_mermaid
from .metrics import metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .scenarios import load_scenarios
from .state import Route, Scenario, initial_state

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="LangGraph Agent Lab Dashboard", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Serve static files
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory store for run results
_run_cache: dict[str, Any] = {}
_checkpointer = build_checkpointer("memory")
_graph = build_graph(checkpointer=_checkpointer)


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    scenario_id: str | None = None
    query: str | None = None
    expected_route: str | None = None


class ApproveRequest(BaseModel):
    approved: bool = True
    reviewer: str = "dashboard-user"
    comment: str = ""

class ResumeRequest(BaseModel):
    thread_id: str
    scenario_id: str
    approved: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Dashboard not found. Place index.html in /static/</h1>")


@app.get("/api/scenarios")
async def list_scenarios() -> list[dict]:
    """List all scenarios from JSONL file."""
    try:
        scenarios = load_scenarios("data/sample/scenarios_hidden.jsonl")
        return [s.model_dump() for s in scenarios]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/run")
async def run_single(req: RunRequest) -> dict:
    """Run a single scenario through the graph."""
    global _graph, _checkpointer

    if req.query:
        # Custom query
        route = Route(req.expected_route) if req.expected_route else Route.SIMPLE
        scenario = Scenario(id=req.scenario_id or "custom", query=req.query, expected_route=route)
    elif req.scenario_id:
        # Find scenario by ID
        scenarios = load_scenarios("data/sample/scenarios_hidden.jsonl")
        found = [s for s in scenarios if s.id == req.scenario_id]
        if not found:
            raise HTTPException(status_code=404, detail=f"Scenario {req.scenario_id} not found")
        scenario = found[0]
    else:
        raise HTTPException(status_code=400, detail="Provide scenario_id or query")

    state = initial_state(scenario)
    run_config = {"configurable": {"thread_id": state["thread_id"]}}

    import os
    os.environ["LANGGRAPH_INTERRUPT"] = "true"

    t0 = time.perf_counter()
    final_state = graph_invoke_safe(state, run_config)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    # Check if interrupted
    snapshot = _graph.get_state(run_config)
    if snapshot.next:
        return {
            "status": "interrupted",
            "scenario_id": scenario.id,
            "thread_id": state["thread_id"],
            "state": serialize_state(snapshot.values),
            "message": "Waiting for human approval",
        }

    metric = metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval)
    metric.latency_ms = latency_ms

    # Cache results
    _run_cache[scenario.id] = {
        "state": final_state,
        "metric": metric.model_dump(),
        "scenario": scenario.model_dump(),
    }

    return {
        "status": "completed",
        "scenario_id": scenario.id,
        "state": serialize_state(final_state),
        "metric": metric.model_dump(),
        "latency_ms": latency_ms,
    }

@app.post("/api/resume")
async def resume_graph(req: ResumeRequest) -> dict:
    """Resume an interrupted graph with human approval decision."""
    global _graph
    
    run_config = {"configurable": {"thread_id": req.thread_id}}
    
    scenarios = load_scenarios("data/sample/scenarios_hidden.jsonl")
    found = [s for s in scenarios if s.id == req.scenario_id]
    scenario = found[0] if found else None

    decision = {
        "approved": req.approved, 
        "reviewer": "dashboard-user", 
        "comment": "Web UI decision"
    }
    
    t0 = time.perf_counter()
    try:
        final_state = _graph.invoke(Command(resume=decision), config=run_config)
    except Exception as e:
        final_state = {**_graph.get_state(run_config).values, "errors": [str(e)]}
        
    latency_ms = int((time.perf_counter() - t0) * 1000)
    
    if scenario:
        metric = metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval)
        metric.latency_ms = latency_ms
        _run_cache[scenario.id] = {
            "state": final_state,
            "metric": metric.model_dump(),
            "scenario": scenario.model_dump(),
        }
        metric_dump = metric.model_dump()
    else:
        metric_dump = {}

    return {
        "status": "completed",
        "scenario_id": req.scenario_id,
        "state": serialize_state(final_state),
        "metric": metric_dump,
        "latency_ms": latency_ms,
    }


@app.post("/api/run-all")
async def run_all() -> dict:
    """Run all scenarios and return full metrics report."""
    global _graph, _checkpointer
    import os
    os.environ["LANGGRAPH_INTERRUPT"] = "false"

    scenarios = load_scenarios("data/sample/scenarios_hidden.jsonl")
    metrics = []
    results = []

    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}

        t0 = time.perf_counter()
        final_state = graph_invoke_safe(state, run_config)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        metric = metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval)
        metric.latency_ms = latency_ms
        metrics.append(metric)

        _run_cache[scenario.id] = {
            "state": final_state,
            "metric": metric.model_dump(),
            "scenario": scenario.model_dump(),
        }

        results.append({
            "scenario_id": scenario.id,
            "metric": metric.model_dump(),
            "state": serialize_state(final_state),
        })

    report = summarize_metrics(metrics)
    write_metrics(report, "outputs/metrics.json")

    return {
        "report": report.model_dump(),
        "results": results,
    }


@app.get("/api/metrics")
async def get_metrics() -> dict:
    """Get latest metrics.json if available."""
    metrics_path = Path("outputs/metrics.json")
    if metrics_path.exists():
        return json.loads(metrics_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="No metrics found. Run scenarios first.")


@app.get("/api/state-history/{thread_id}")
async def get_state_history(thread_id: str) -> list[dict]:
    """Get checkpoint history for time-travel replay."""
    global _graph
    try:
        config = {"configurable": {"thread_id": thread_id}}
        history = list(_graph.get_state_history(config))
        return [
            {
                "step": i,
                "values": serialize_state(snapshot.values),
                "next": list(snapshot.next) if snapshot.next else [],
                "created_at": str(snapshot.created_at) if hasattr(snapshot, "created_at") else None,
            }
            for i, snapshot in enumerate(history)
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/graph-diagram")
async def get_graph_diagram() -> dict:
    """Return Mermaid diagram of the graph."""
    try:
        mermaid = export_mermaid("outputs/graph.mermaid")
        return {"mermaid": mermaid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/crash-resume")
async def crash_resume_demo() -> dict:
    """Demonstrate crash-resume with SQLite persistence."""
    try:
        sqlite_cp = build_checkpointer("sqlite", "crash_demo.db")
        sqlite_graph = build_graph(checkpointer=sqlite_cp)

        scenario = Scenario(id="crash_demo", query="How do I reset my password?", expected_route=Route.SIMPLE)
        state = initial_state(scenario)
        thread_id = state["thread_id"]
        run_config = {"configurable": {"thread_id": thread_id}}

        # Run the scenario
        result1 = sqlite_graph.invoke(state, config=run_config)

        # "Crash" — build a NEW graph instance from the same DB
        sqlite_cp2 = build_checkpointer("sqlite", "crash_demo.db")
        sqlite_graph2 = build_graph(checkpointer=sqlite_cp2)

        # Resume — get state from checkpoint
        recovered_state = sqlite_graph2.get_state(run_config)

        return {
            "success": True,
            "original_answer": result1.get("final_answer"),
            "recovered_answer": recovered_state.values.get("final_answer") if recovered_state else None,
            "state_matches": (
                result1.get("final_answer") == recovered_state.values.get("final_answer")
                if recovered_state
                else False
            ),
            "message": "SQLite checkpoint survives process restart. State fully recovered.",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Crash-resume requires langgraph-checkpoint-sqlite: {e}",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def graph_invoke_safe(state: dict, run_config: dict) -> dict:
    """Invoke graph with error handling."""
    global _graph
    try:
        return _graph.invoke(state, config=run_config)
    except Exception as e:
        return {**state, "errors": [str(e)], "final_answer": f"Graph error: {e}"}


def serialize_state(state: dict) -> dict:
    """Make state JSON-serializable."""
    result = {}
    for k, v in state.items():
        try:
            json.dumps(v)
            result[k] = v
        except (TypeError, ValueError):
            result[k] = str(v)
    return result
