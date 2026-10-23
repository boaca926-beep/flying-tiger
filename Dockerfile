FROM python:3.12-slim-bookworm

ENV PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/app/.venv/bin:$PATH" \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/

RUN useradd -m appuser
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && chown -R appuser:appuser /app/.venv

COPY --chown=appuser:appuser . .

USER appuser
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=3s --start-period=30s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health').status==200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]