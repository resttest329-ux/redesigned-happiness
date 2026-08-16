FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv pip install -r requirements.txt

COPY . .


FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home appuser

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 5000

CMD ["python", "main.py"]
