# Use a Python base image with uv pre-installed or install it
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Set the working directory
WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy the uv lock and pyproject.toml
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Second stage: run the app
FROM python:3.12-slim-bookworm

WORKDIR /app

# Copy the virtual environment from the builder
COPY --from=builder /app/.venv /app/.venv

# Add the virtual environment to the PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app

# The build context is the backend/ directory itself; nest it under
# /app/backend so `backend` is importable as a top-level package
# (uvicorn backend.main:app, celery -A backend.celery_app, python -m backend.seed).
COPY . ./backend

# Expose the port
EXPOSE 8000

# The command is overridden by docker-compose, but we provide a default
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips='*'"]
