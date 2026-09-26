.PHONY: up down migrate test test-unit test-integration lint format

up:
	docker compose up --build -d

down:
	docker compose down -v

migrate:
	alembic upgrade head

validate-contracts:
	python -c "from src.attest.contracts import load_contracts; load_contracts('contracts'); print('All contracts valid.')"

test: validate-contracts
	pytest tests/ -v --tb=short

test-unit:
	pytest tests/unit/ -v --tb=short

test-integration:
	pytest tests/integration/ -v --tb=short -m integration

lint:
	ruff check src/ tests/
	mypy src/

format:
	ruff format src/ tests/
	ruff check --fix src/ tests/

bench:
	@echo "Benchmark not yet implemented (Phase 5)"

report:
	@echo "Report not yet implemented (Phase 5)"
