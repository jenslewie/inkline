.PHONY: format lint format-check typecheck security deps-audit test test-cov check

format:
	uv run ruff format .
	uv run ruff check . --fix

lint:
	uv run ruff check .

format-check:
	uv run ruff format --check .

typecheck:
	uv run pyright

security:
	uv run bandit -c pyproject.toml -r packages

deps-audit:
	uv export --frozen --all-packages --all-extras --no-hashes --format requirements.txt --output-file /tmp/inkline-requirements.txt
	uv run pip-audit -r /tmp/inkline-requirements.txt

test:
	uv run pytest -q

test-cov:
	uv run pytest -q --cov=packages --cov-report=term-missing

check: lint format-check test
