#!/usr/bin/env bash
set -euo pipefail
cd /mnt/c/Global\ Multilingual\ Live\ Chat\ Support\ Agent
ip=$(hostname -I | cut -d' ' -f1)
source .venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://support_user:support_pass@localhost:5432/support_agent"
export REDIS_URL="redis://localhost:6379/0"
export QDRANT_URL="http://localhost:6333"
export QDRANT_API_KEY=""
export ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000,http://${ip}:3000"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
