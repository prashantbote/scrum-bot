# Scrum Bot backend (plan §13). Windows without make: run the commands after each target by hand.
COMPOSE = docker compose -f ../infra/docker-compose.yml
RUN = uv run

.PHONY: dev down migrate seed run api worker test test-all lint typecheck openapi voices evals check

dev:            ## start Postgres+pgvector, Redis, Temporal, Mailpit, SeaweedFS
	$(COMPOSE) up -d postgres redis temporal mailpit seaweedfs
	uv sync

down:
	$(COMPOSE) down

migrate:
	$(RUN) alembic upgrade head

seed: migrate    ## Neha's "Payments" story week (dev personas u-neha, u-deepa, u-rahul, u-vikram)
	$(RUN) python scripts/seed.py

api:
	$(RUN) uvicorn scrum_api.main:app --port 8800 --reload --reload-dir services --reload-dir packages

worker:
	$(RUN) scrum-worker all

run:            ## API + all workers (two processes)
	$(RUN) scrum-worker all & $(RUN) uvicorn scrum_api.main:app --port 8800

test:           ## offline suite (heuristic engine, fakes); DB/Temporal tests need `make dev`
	$(RUN) pytest -m "not llm and not voice_models"

test-all:       ## + real Piper/Whisper speech and the open-source LLM evals
	$(RUN) pytest

evals:
	$(RUN) pytest tests/evals -m llm -s

voices:         ## download the Piper voice used by SCRUM_TTS_PROVIDER=piper
	uv sync --extra voice
	$(RUN) python -m piper.download_voices en_US-lessac-medium --download-dir .data/piper

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check packages services scripts tests
	$(RUN) lint-imports

typecheck:
	$(RUN) mypy packages services

openapi:
	$(RUN) python scripts/export_openapi.py

check: lint typecheck test
	$(RUN) python scripts/export_openapi.py --check
	$(RUN) alembic check
