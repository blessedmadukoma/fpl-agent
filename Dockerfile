# The Release 1 web pages only: no agent, no model client and no keys.
FROM python:3.12.13-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --only-group web --no-install-project

FROM python:3.12.13-slim-trixie
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /app/.venv .venv
COPY src src
COPY exports/evals exports/evals
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/src PYTHONUNBUFFERED=1
USER app
EXPOSE 10000
# Render sets PORT; the shell form lets the command read it.
CMD ["sh", "-c", "exec uvicorn fpl.web.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
