# One multi-stage image, three targets: api, worker (orchestrator/intelligence/delivery), voice.
#   docker build -f docker/Dockerfile --target api    -t scrum-bot/api .
#   docker build -f docker/Dockerfile --target worker -t scrum-bot/worker .
#   docker build -f docker/Dockerfile --target voice  -t scrum-bot/voice .
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
WORKDIR /app
# WeasyPrint (PDF digests) needs Pango.
RUN apt-get update && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -r app && useradd -r -g app -d /app app

FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra pdf

FROM deps AS app
COPY packages packages
COPY services services
COPY migrations migrations
COPY scripts scripts
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --extra pdf
ENV PATH="/app/.venv/bin:$PATH"

FROM app AS api
USER app
EXPOSE 8800
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8800/healthz')"
CMD ["uvicorn", "scrum_api.main:app", "--host", "0.0.0.0", "--port", "8800", "--proxy-headers"]

FROM app AS worker
USER app
CMD ["scrum-worker", "orchestrator", "intelligence", "delivery"]

FROM app AS voice
RUN uv sync --frozen --no-dev --extra pdf --extra voice \
    && python -m piper.download_voices en_US-lessac-medium --download-dir /app/.data/piper \
    && python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')" \
    && chown -R app:app /app/.data
USER app
ENV SCRUM_MEETING_PROVIDER=livekit SCRUM_STT_PROVIDER=whisper SCRUM_TTS_PROVIDER=piper
CMD ["scrum-worker", "voice"]
