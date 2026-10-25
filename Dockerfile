# HTTP service for the portfolio risk tools: /health, /analytics, /policy.
# Make.com, ngrok and the LLM stay outside the container.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.cache/huggingface \
    OMP_NUM_THREADS=1

WORKDIR /app

# CPU-only PyTorch first, then the pinned service dependencies.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0
COPY requirements-service.txt .
RUN pip install -r requirements-service.txt

# Download the embedding model at build time so the container never fetches
# it at runtime (no network call on startup, no download on each cold start).
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY analytics/ analytics/
COPY policy/ policy/
COPY data/mock_prices.csv data/mock_prices.csv

# Run as an unprivileged user; use only the model cached above.
RUN useradd --create-home app && chown -R app:app /app
USER app
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    RETRIEVAL_WARM_UP=1 \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health', timeout=4)"

# PORT is set by the platform (Render injects its own); 8000 locally.
# uvicorn's access log is off because it records full URLs, including
# /policy query text; the service logs method, path, status and time itself.
CMD ["sh", "-c", "uvicorn service:app --app-dir analytics --host 0.0.0.0 --port ${PORT} --no-access-log"]
