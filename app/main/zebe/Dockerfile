FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv pip install -r requirements.txt

COPY . .


FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev curl && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

RUN chmod +x /app/entry.sh && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entry.sh"]
