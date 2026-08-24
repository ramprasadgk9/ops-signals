FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
RUN pip install -r requirements.txt

COPY backend ./backend
COPY intelligence ./intelligence
COPY experiments ./experiments
COPY config.yaml config.yaml
COPY config ./config
COPY docs ./docs

CMD ["python", "-m", "backend.app.mcp_server"]
