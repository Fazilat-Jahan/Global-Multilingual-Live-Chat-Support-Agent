# Global Multilingual Live Chat Support Agent

Production-grade MVP of an embeddable, multilingual, multi-agent AI customer support system. See `Global_Multilingual_Live_Chat_Support_Agent.md` for the full spec and `CLAUDE.md` for the phased build plan.

## Phase 1 — Foundation (current)

### Prerequisites
- Python 3.11+
- Docker + Docker Compose

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

cp .env.example .env
# then edit .env and set GEMINI_API_KEY
```

### Run local infrastructure (Postgres, Redis, Qdrant)

```bash
docker compose up -d
```

### Run the API

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/health`

### Verify Gemini connectivity

```bash
python -m backend.scripts.test_gemini_connection
```

This requires a valid `GEMINI_API_KEY` in `.env` and network access.
