from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.admin import router as admin_router
from backend.api.health import router as health_router
from backend.api.tickets import router as tickets_router
from backend.config import get_settings
from backend.middleware.origin_policy import OriginPolicyMiddleware
from backend.websocket.handler import router as websocket_router

settings = get_settings()

app = FastAPI(title="Global Multilingual Live Chat Support Agent")

# Origin policy (spec 12.3). The embedded widget runs in its own iframe on
# the widget host and talks to this backend from that origin; any other
# direct API/WebSocket access must come from an explicitly allowed origin
# (ALLOWED_ORIGINS, comma-separated — default is the local dev frontend).
# CORSMiddleware below emits the spec'd headers for allowed origins; the
# outer OriginPolicyMiddleware additionally rejects disallowed origins
# server-side (HTTP 403 / refused WebSocket upgrade) so they can never
# reach route logic, not just fail to read the response in a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=86400,
)
app.add_middleware(OriginPolicyMiddleware, allowed_origins=settings.allowed_origin_list)

app.include_router(health_router)
app.include_router(tickets_router)
app.include_router(admin_router)
app.include_router(websocket_router)
