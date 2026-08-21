FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY backend ./backend
COPY knowledge_base ./knowledge_base

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# $PORT is provided by Railway/Render at runtime; 8000 is the local/default fallback.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
