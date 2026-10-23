# check update

FROM python:3.12-slim

# 1. Tvinga UTF-8 för att lösa UnicodeEncodeError (Alternativ A)
ENV PYTHONUTF8=1
ENV PYTHONIOENCODING=utf-8
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# 2. Installera uv (verktyget du använder)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 3. Sätt arbetskatalog
WORKDIR /app

# 4. Kopiera in dina beroendefiler först (för att utnyttja Docker-cache)
COPY pyproject.toml uv.lock ./

# 5. Installera beroenden med uv
RUN uv sync --frozen

# 6. Kopiera resten av din applikationskod
COPY . .

# 7. Exponera porten som Streamlit kör på
EXPOSE 8501

# 8. Starta appen
CMD ["uv", "run", "streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]