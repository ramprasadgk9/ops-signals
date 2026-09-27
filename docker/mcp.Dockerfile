FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml ./
# CPU-only torch first (sentence-transformers needs it): PyPI's default linux/amd64 wheel bundles
# several GB of CUDA libraries the backend never uses. requirements.txt then finds torch satisfied.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
RUN pip install -r requirements.txt

COPY backend ./backend
COPY intelligence ./intelligence
COPY experiments ./experiments
COPY config.yaml config.yaml
COPY config ./config
COPY docs ./docs
# Ask Ops Signals answers from README.md as well as docs/ (knowledge_bootstrap.py).
COPY README.md README.md

CMD ["python", "-m", "backend.app.mcp_server"]
