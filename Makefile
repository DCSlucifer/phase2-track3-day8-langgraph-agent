.PHONY: install test lint typecheck run-scenarios grade-local clean ui

install:
	pip install -e '.[dev]'

test:
	pytest

lint:
	ruff check src tests

typecheck:
	mypy src

run-scenarios:
	python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json

grade-local:
	python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json

ui:
	uvicorn langgraph_agent_lab.web:app --host 0.0.0.0 --port 8000 --reload

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov dist build *.egg-info outputs/*.json checkpoints.db crash_demo.db
