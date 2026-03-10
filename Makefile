.PHONY: run test test-fast lint typecheck docker-up docker-down build-web clean web-lint web-typecheck ci

# ── Development ────────────────────────────────────────────

run:
	uvicorn registry.api.app:app --reload --host 0.0.0.0 --port 8000

# ── Testing ────────────────────────────────────────────────

test:
	python -m pytest tests/ -v --tb=short

test-fast:
	python -m pytest tests/ -v --tb=short --ignore=tests/registry/test_phase_h.py

# ── Code Quality ───────────────────────────────────────────

lint:
	ruff check .

lint-fix:
	ruff check --fix .

typecheck:
	mypy registry subnet --ignore-missing-imports

# ── Docker ─────────────────────────────────────────────────

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

# ── Web Dashboard ──────────────────────────────────────────

build-web:
	cd web && npm install && npm run build

dev-web:
	cd web && npm run dev

web-lint:
	cd web && npm run lint

web-typecheck:
	cd web && npx tsc --noEmit

# ── Database Migrations ────────────────────────────────────

migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(msg)"

migrate-check:
	alembic check

# ── CI composite ──────────────────────────────────────────

ci: lint typecheck test web-lint build-web

# ── Cleanup ────────────────────────────────────────────────

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache htmlcov .coverage
