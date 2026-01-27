# Oceans of NYC - Just Commands
# Run `just` to see all available commands

# Load environment variables from .env file
set dotenv-load

# Configure uv to use only its managed Python installations
export UV_PYTHON_PREFERENCE := "only-managed"

# Default recipe lists all commands
default:
    @just --list

# ==================== Setup ====================

# Install all dependencies (production + dev + test)
install:
    uv pip install -e ".[dev,test]"

# Install production dependencies only
install-prod:
    uv pip install -e .

# Install dev dependencies only
install-dev:
    uv pip install -e ".[dev]"

# Install test dependencies only
install-test:
    uv pip install -e ".[test]"

# Set up pre-commit hooks
setup-hooks:
    uv run pre-commit install

# Full project setup (install + hooks)
setup: install setup-hooks
    @echo "✓ Project setup complete"

# ==================== Testing ====================

# Run all tests
test:
    uv run python -m pytest

# Run unit tests only (fast, no external dependencies)
test-unit:
    uv run python -m pytest -m unit -v

# Run database tests (requires TEST_DATABASE_URL)
test-db:
    uv run python -m pytest -m db -v

# Run integration tests (requires external services)
test-integration:
    uv run python -m pytest -m integration -v

# Run tests with coverage report
test-coverage:
    uv run python -m pytest --cov=. --cov-report=html --cov-report=term-missing

# Run tests and open coverage report
test-coverage-open: test-coverage
    open htmlcov/index.html

# Run specific test file
test-file FILE:
    uv run python -m pytest {{FILE}} -v

# Run tests matching a pattern
test-pattern PATTERN:
    uv run python -m pytest -k {{PATTERN}} -v

# Run tests in watch mode (requires pytest-watch)
test-watch:
    uv run ptw -- -v

# ==================== Linting & Formatting ====================

# Run all linters and formatters
lint: lint-ruff lint-mypy

# Run ruff linter
lint-ruff:
    uv run ruff check .

# Run ruff linter with auto-fix
lint-ruff-fix:
    uv run ruff check . --fix

# Run ruff formatter
format:
    uv run ruff format .

# Check formatting without making changes
format-check:
    uv run ruff format . --check

# Run mypy type checker
lint-mypy:
    uv run mypy .

# Run all checks (lint + format check)
check: lint format-check
    @echo "✓ All checks passed"

# Fix all auto-fixable issues (ruff + format)
fix: lint-ruff-fix format
    @echo "✓ Auto-fixes applied"

# ==================== Pre-commit ====================

# Run pre-commit on all files
precommit:
    uv run pre-commit run --all-files

# Run pre-commit on staged files only
precommit-staged:
    uv run pre-commit run

# Update pre-commit hooks to latest versions
precommit-update:
    uv run pre-commit autoupdate

# ==================== Database ====================

# Connect to the database (requires DATABASE_URL)
db-connect:
    psql $DATABASE_URL

# Run database migrations
db-migrate:
    @echo "No migrations system yet"

# Reset test database
db-reset-test:
    @echo "Resetting test database..."
    dropdb oceansofnyc_test || true
    createdb oceansofnyc_test

# ==================== Modal Deployment ====================

# Deploy all Modal functions
deploy:
    uv run modal deploy modal_app.py

# Deploy in dev mode (faster, no cold starts)
deploy-dev:
    uv run modal serve modal_app.py

# Run Modal function locally
deploy-run FUNCTION:
    uv run modal run modal_app.py::{{FUNCTION}}

# View Modal app logs
deploy-logs:
    modal app logs oceans-of-nyc

# List Modal deployments
deploy-list:
    modal app list

# Stop Modal deployment
deploy-stop:
    modal app stop oceans-of-nyc

# ==================== Development ====================

# Start a Python REPL with project modules loaded
repl:
    uv run python -i -c "from database import SightingsDatabase; from post.bluesky import BlueskyClient; print('Modules loaded: SightingsDatabase, BlueskyClient')"

# Run the CLI
cli *ARGS:
    uv run python main.py {{ARGS}}

# Run a Python script
run SCRIPT:
    uv run python {{SCRIPT}}

# ==================== Utilities ====================

# Clean build artifacts and caches
clean:
    rm -rf .pytest_cache
    rm -rf htmlcov
    rm -rf .coverage
    rm -rf .mypy_cache
    rm -rf .ruff_cache
    rm -rf dist
    rm -rf build
    rm -rf *.egg-info
    find . -type d -name __pycache__ -exec rm -rf {} +
    @echo "✓ Cleaned build artifacts"

# Show dependency tree
deps:
    uv pip list

# Check for outdated dependencies
deps-outdated:
    uv pip list --outdated

# ==================== CI/CD ====================

# Run CI checks locally (same as GitHub Actions will run)
ci: check test-unit
    @echo "✓ CI checks passed"

# Run full CI pipeline
ci-full: check test
    @echo "✓ Full CI checks passed"

# ==================== Documentation ====================

# Generate test coverage badge (requires coverage-badge)
docs-badge:
    uv run coverage-badge -o docs/coverage.svg -f

# Serve documentation locally (if we add docs)
docs-serve:
    @echo "No docs system yet"

# ==================== Modal Specific ====================

# Post a batch of sightings (via Modal)
modal-post SIZE="4":
    uv run modal run modal_app.py::post_batch --batch-size={{SIZE}}

# Post in dry-run mode
modal-post-dry SIZE="4":
    uv run modal run modal_app.py::post_batch --batch-size={{SIZE}} --dry-run=true

# Get database statistics
modal-stats:
    uv run modal run modal_app.py::get_stats

# Update TLC vehicle data
modal-update-tlc:
    uv run modal run modal_app.py::update_tlc_vehicles

# Backfill image hashes
modal-backfill-hashes SIZE="10":
    uv run modal run modal_app.py::backfill_image_hashes --batch-size={{SIZE}}

# Generate web data (vehicles.json)
modal-generate-web:
    uv run modal run modal_app.py::generate_web_data

# ==================== Shortcuts ====================

# Quick test + lint cycle
quick: test-unit lint-ruff
    @echo "✓ Quick checks passed"

# Full local validation (what CI runs)
validate: ci
    @echo "✓ Local validation complete"

# Prepare for commit (format, lint, test)
prepare: fix test-unit
    @echo "✓ Ready to commit"
