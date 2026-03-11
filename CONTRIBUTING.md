# Contributing to Modelionn

Thank you for your interest in contributing! This document covers the development setup,
coding standards, and pull-request process.

## Development Setup

### Prerequisites

- Python 3.10+
- Node.js 20+ (for the web dashboard)
- Docker & Docker Compose (for full-stack testing)

### Installation

```bash
# Clone the repo
git clone https://github.com/your-org/modelionn.git
cd modelionn

# Create a virtual environment
python -m venv .venv && source .venv/bin/activate

# Install in dev mode
pip install -e ".[dev]"

# Copy environment file
cp .env.example .env
```

### Running the Registry

```bash
# Development server with auto-reload
uvicorn registry.api.app:app --reload

# Or via Make
make run
```

### Running the Dashboard

```bash
cd web
npm install
npm run dev    # http://localhost:3000
```

## Testing

```bash
# Fast tests (no Docker services required)
make test-fast

# Full suite (requires Redis for Celery tests)
make test

# Run a specific test file
pytest tests/registry/test_phase_f.py -v
```

Test breakdown:

- `tests/registry/` — API routes, middleware, core logic, security
- `tests/subnet/` — Consensus, reward, anti-sybil, miner, validator
- `tests/sdk/` — Client caching, connection pooling
- `tests/cli/` — CLI commands
- `tests/e2e/` — End-to-end integration pipeline

## Code Style

We use **ruff** for linting and **mypy** for type checking:

```bash
make lint        # ruff check .
make typecheck   # mypy registry subnet --ignore-missing-imports
```

Key rules:

- Line length: 100 characters
- Target: Python 3.10+
- Ruff selects: E, F, I, N, W, UP
- Type annotations required for all public functions

## Pull Request Process

1. **Branch** off `main` with a descriptive name: `feat/nl-search`, `fix/rate-limit-429`
2. **Write tests** for any new functionality
3. **Run the full check**: `make lint && make typecheck && make test-fast`
4. **Open a PR** with a clear description of what changed and why
5. CI will run automatically (lint → mypy → pytest → determinism checks)

### Commit Messages

Use conventional commits:

- `feat: add natural-language search endpoint`
- `fix: handle empty embedding response`
- `docs: update README with Phase J features`
- `test: add audit trail integration tests`

## Architecture Notes

- **FastAPI** with async SQLAlchemy for the registry
- **Pydantic v2** for all request/response schemas
- **SQLAlchemy 2.0** async ORM with aiosqlite (dev) / asyncpg (production)
- **Celery** with Redis broker for async proof-generation jobs
- **Next.js 14** App Router for the web dashboard
- Middleware order matters: RequestID → SecurityHeaders → CSRF → Tenant → RateLimit → Metrics (outermost)

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
