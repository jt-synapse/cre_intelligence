FROM ghcr.io/astral-sh/uv:0.13.9 AS uv
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock alembic.ini ./
COPY cre ./cre
COPY migrations ./migrations
COPY contracts ./contracts
RUN uv sync --frozen --no-dev --no-editable && useradd -r -u 10001 appuser
USER appuser
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn","cre.main:app","--host","0.0.0.0","--port","8000"]
