# Repository Guidelines

## Project Structure & Module Organization
- `api/`: FastAPI app entry points, routes, websocket management, and metrics.
- `core/`: Domain logic (models, risk, scheduling, auth, analytics, ML, events).
- `integrations/`: Exchange clients and data integrations (e.g., `integrations/exchanges`).
- `agents/`: Trading agent orchestration and specialist components (analysts, strategist, executor).
- `config/`: Stage and strategy configuration YAMLs.
- `memory/`: In-memory and persistent caches, journaling, and learning utilities.
- `migrations/`: SQL schema migrations.
- `static/`: Web UI assets (HTML/CSS/JS).
- `tests/`: `unit/` and `integration/` test suites.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: Install runtime and test dependencies.
- `python main.py`: Run the API server using `.env` configuration.
- `STAGE=stage2 python main.py`: Run a specific stage.
- `SIMULATION_MODE=true python main.py`: Force simulation mode.
- `DEBUG=true python main.py`: Enable auto-reload via Uvicorn.
- `pytest`: Run unit tests (integration tests are excluded by default).
- `pytest -m integration -v`: Run integration tests against Binance testnet.

## Coding Style & Naming Conventions
- Python code follows PEP 8 with 4-space indentation.
- Naming: `snake_case` for functions/vars, `CapWords` for classes, `UPPER_SNAKE_CASE` for constants.
- Prefer explicit type hints when adding new public APIs or data models.
- No formatter is configured; keep changes consistent with surrounding style.

## Testing Guidelines
- Framework: `pytest` with `pytest-asyncio`.
- Unit tests live in `tests/unit/`; integration tests in `tests/integration/`.
- Integration tests require `BINANCE_TESTNET_KEY` and `BINANCE_TESTNET_SECRET`.
- Use descriptive test names (e.g., `test_get_ticker_returns_price`).

## Commit & Pull Request Guidelines
- Commit messages follow a simple conventional pattern like `fix: ...` or `feat: ...`.
- Keep the subject short, imperative, and scoped to the change.
- PRs should include: purpose summary, testing performed, and any required config or env changes.

## Security & Configuration Tips
- Use `.env.example` as the baseline for local configuration.
- Do not commit real API keys; keep secrets in local `.env` files.
- Default behavior falls back to simulation mode when exchange keys are missing.
