# Build context is the repo root (see docker-compose.yml) so this can
# copy the shared workspace package in alongside the service itself.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Copy just the workspace metadata first so dependency install is cached
# unless pyproject/lock files actually change.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/pyproject.toml
COPY auth/pyproject.toml auth/pyproject.toml

RUN uv sync --frozen --package auth --no-install-project

# Now copy the actual source and install the project itself.
COPY shared shared
COPY auth auth
RUN uv sync --frozen --package auth

EXPOSE 8000
CMD ["uv", "run", "--package", "auth", "uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
