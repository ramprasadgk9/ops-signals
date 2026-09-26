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

# Bake the operational-memory embedding model (config.yaml memory.embedding.model) into the image,
# so the first start needs no HuggingFace download.
ENV HF_HOME=/app/.cache/huggingface
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY backend ./backend
COPY intelligence ./intelligence
COPY experiments ./experiments
COPY config.yaml config.yaml
COPY config ./config
COPY sql ./sql
COPY docs ./docs
# Ask Ops Signals answers from README.md as well as docs/ (knowledge_bootstrap.py).
COPY README.md README.md

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
