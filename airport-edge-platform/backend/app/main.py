"""Application startup, local database seeding, middleware, and WebSocket route."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import CORS_ORIGINS
from app.database import Base, SessionLocal, engine, migrate_schema
from app.events import event_hub
from app.services.devices import seed_devices
from app.services.passengers import seed_passengers
from app.services.rules import seed_rules

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Create/update local schema and seed synthetic records before serving requests."""

    Base.metadata.create_all(bind=engine)
    migrate_schema()
    with SessionLocal() as db:
        seed_passengers(db)
        seed_devices(db)
        seed_rules(db)
    yield


app = FastAPI(
    title="Airport Edge AI Platform",
    version="1.0.0",
    description="Local-first airport device simulation; all identity profiles are synthetic.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket) -> None:
    """Keep an event-stream client connected until it disconnects."""

    await event_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await event_hub.disconnect(websocket)
