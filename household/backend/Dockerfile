# Build context is the repo root (see docker-compose.yml).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY household/backend/pyproject.toml household/backend/pyproject.toml

RUN uv sync --frozen --package household-backend --no-install-project

COPY shared shared
COPY household/backend household/backend
RUN uv sync --frozen --package household-backend

EXPOSE 8000
CMD ["uv", "run", "--package", "household-backend", "uvicorn", "household_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
