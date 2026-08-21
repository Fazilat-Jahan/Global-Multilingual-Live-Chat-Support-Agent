from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.health import router as health_router
from backend.api.tickets import router as tickets_router
from backend.config import get_settings
from backend.websocket.handler import router as websocket_router

settings = get_settings()

app = FastAPI(title="Global Multilingual Live Chat Support Agent")

# Permissive by design: this is an embeddable widget meant to run on
# arbitrary client websites, not a first-party single-origin app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(tickets_router)
app.include_router(websocket_router)
