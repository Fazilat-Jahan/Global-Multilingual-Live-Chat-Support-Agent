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

# Phase 13 (spec 6.2): run Alembic migrations before starting the app so
# the schema is always up to date on deployment. The `alembic` CLI is run
# from the backend/ directory (where alembic.ini lives); uvicorn starts
# from the project root.
CMD ["sh", "-c", "cd backend && alembic upgrade head && cd /app && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
