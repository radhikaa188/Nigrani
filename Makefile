.PHONY: all run run-backend run-frontend test test-backend test-frontend lint lint-backend lint-frontend fmt fmt-backend fmt-frontend

all: lint test

run:
	@echo "Starting backend and frontend..."
	(cd backend && uvicorn app.main:app --reload) & (cd frontend && npm run dev)

run-backend:
	cd backend && uvicorn app.main:app --reload

run-frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	@if [ -d backend/tests ] && [ "$$(find backend/tests -name 'test_*.py' 2>/dev/null)" != "" ]; then \
		cd backend && pytest; \
	else \
		echo "Backend: no tests found (backend/tests not configured yet)"; \
	fi

test-frontend:
	@if grep -q '"test":' frontend/package.json 2>/dev/null; then \
		cd frontend && npm test -- --passWithNoTests; \
	else \
		echo "Frontend: no tests found (tests not configured yet)"; \
	fi

lint: lint-backend lint-frontend

lint-backend:
	cd backend && ruff check .

lint-frontend:
	cd frontend && npm run lint

fmt: fmt-backend fmt-frontend

fmt-backend:
	cd backend && ruff format . && ruff check --fix .

fmt-frontend:
	cd frontend && npm run fmt
