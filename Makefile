.PHONY: setup test lint fmt mypy run mcp eval docker memory clean

setup:
	python -m venv .venv
	.venv/bin/pip install -e ".[dev]"

test:
	OMP_NUM_THREADS=1 .venv/bin/pytest tests/ -v --tb=short

lint:
	.venv/bin/ruff check src/ tests/

fmt:
	.venv/bin/ruff format src/ tests/

mypy:
	.venv/bin/mypy src/companylens/

run:
	OMP_NUM_THREADS=1 .venv/bin/uvicorn src.companylens.api.main:app --host 0.0.0.0 --port 8000 --workers 1 --reload

mcp:
	.venv/bin/python -m companylens.mcp_server.server

eval:
	.venv/bin/python eval/run_eval.py

docker:
	docker build -t companylens:latest .
	docker run --rm -p 8000:8000 --env-file .env companylens:latest

memory:
	docker build -t companylens:latest .
	.venv/bin/python scripts/measure_memory.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build *.egg-info
