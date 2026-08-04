FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}" \
    SQLITE_DATABASE_PATH=/var/lib/sombreado/sombreado.sqlite

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.1 /uv /uvx /usr/local/bin/

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/sombreado \
    && chown app:app /var/lib/sombreado

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && uv sync --frozen --no-dev \
    && chown -R app:app /app

USER app

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn sombreado.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
