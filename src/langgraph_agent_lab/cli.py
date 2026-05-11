"""CLI for the lab."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .graph import build_graph, export_mermaid
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer
from .report import write_report
from .scenarios import load_scenarios
from .state import initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON."""
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios = load_scenarios(cfg["scenarios_path"])
    checkpointer = build_checkpointer(cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)

    metrics = []
    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}

        # Measure latency per scenario
        t0 = time.perf_counter()
        final_state = graph.invoke(state, config=run_config)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        metric = metric_from_state(final_state, scenario.expected_route.value, scenario.requires_approval)
        metric.latency_ms = latency_ms
        metrics.append(metric)

    # Check crash-resume evidence if using sqlite
    resume_success = False
    if cfg.get("checkpointer") == "sqlite":
        resume_success = _test_crash_resume(cfg.get("database_url"))

    report = summarize_metrics(metrics)
    report.resume_success = resume_success
    write_metrics(report, output)

    # Export Mermaid diagram (bonus)
    try:
        export_mermaid("outputs/graph.mermaid")
    except Exception:
        pass  # Non-critical

    # Generate report
    if cfg.get("report_path"):
        write_report(report, cfg["report_path"])

    typer.echo(f"[OK] Wrote metrics to {output}")
    typer.echo(f"   Total scenarios: {report.total_scenarios}")
    typer.echo(f"   Success rate: {report.success_rate:.0%}")
    typer.echo(f"   Total retries: {report.total_retries}")
    typer.echo(f"   Total interrupts: {report.total_interrupts}")


@app.command("validate-metrics")
def validate_metrics(metrics: Annotated[Path, typer.Option("--metrics")]) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"[OK] Metrics valid. success_rate={report.success_rate:.2%}")


def _test_crash_resume(database_url: str | None) -> bool:
    """Test crash-resume by running a scenario, then reloading from SQLite checkpoint."""
    try:
        from .state import Route, Scenario
        checkpointer = build_checkpointer("sqlite", database_url)
        graph = build_graph(checkpointer=checkpointer)

        # Run a scenario
        scenario = Scenario(id="crash_test", query="How do I reset my password?", expected_route=Route.SIMPLE)
        state = initial_state(scenario)
        thread_id = state["thread_id"]
        run_config = {"configurable": {"thread_id": thread_id}}
        graph.invoke(state, config=run_config)

        # Verify state can be retrieved (simulates crash-resume)
        saved_state = graph.get_state(run_config)
        if saved_state and saved_state.values.get("final_answer"):
            return True
    except Exception:
        pass
    return False


if __name__ == "__main__":
    app()
