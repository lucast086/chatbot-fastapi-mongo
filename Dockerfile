# syntax=docker/dockerfile:1
#
# Two stages. `builder` resolves dependencies; `runtime` is the final image and
# contains no uv, no compilers and no dev dependencies.
#
# The virtualenv lives in /opt/venv rather than inside /app so that bind
# mounting source over /app during development cannot shadow it.

# ---------------------------------------------------------------------------
# base — what builder and runtime share
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

ARG USERNAME=appuser
ARG USER_UID=1000
ARG USER_GID=1000

# uid/gid 1000 is the first non-system user on Linux. Matching it keeps files
# created inside the container from landing on the host owned by root.
RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME"

WORKDIR /app


# ---------------------------------------------------------------------------
# builder — installs production dependencies into /opt/venv
# ---------------------------------------------------------------------------
FROM base AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Manifest and lock only, so this layer is invalidated when dependencies change
# rather than on every source edit.
COPY pyproject.toml uv.lock ./

# --frozen: fail if uv.lock is out of date with pyproject.toml instead of
# silently resolving something different from what was tested.
# --no-install-project: this project is not a package (tool.uv package = false).
RUN uv sync --frozen --no-dev --no-install-project


# ---------------------------------------------------------------------------
# runtime — the final image
# ---------------------------------------------------------------------------
FROM base AS runtime

ARG USERNAME=appuser

COPY --from=builder --chown=$USERNAME:$USERNAME /opt/venv /opt/venv
COPY --chown=$USERNAME:$USERNAME app/ ./app/

USER $USERNAME

EXPOSE 8000

# Uses the Python that is already in the image rather than adding curl. One
# fewer package is one fewer thing to keep patched.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u, sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"

# No --reload in the image: it forks a second process and watches the
# filesystem for nothing.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
