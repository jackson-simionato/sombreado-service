.DEFAULT_GOAL := help

.PHONY: help install start test format lint check pre-commit

help: ## Show available commands
	@printf '%s\n' \
		'Usage: make <target>' \
		'' \
		'  help        Show available commands' \
		'  install     Install project dependencies' \
		'  start       Start the local development server' \
		'  test        Run the test suite' \
		'  format      Format Python files with Ruff' \
		'  lint        Run Ruff lint checks' \
		'  check       Run all non-mutating completion checks' \
		'  pre-commit  Install the pre-commit hooks'

install: ## Install project dependencies
	uv sync

start: ## Start the local development server
	uv run uvicorn sombreado.api.main:app --reload

test: ## Run the test suite
	uv run python -m pytest -q

format: ## Format Python files with Ruff
	uv run ruff format .

lint: ## Run Ruff lint checks
	uv run ruff check .

check: ## Run all non-mutating completion checks
	uv run ruff format --check .
	uv run ruff check .
	uv run python -m pytest -q

pre-commit: ## Install the pre-commit hooks
	uv run pre-commit install
