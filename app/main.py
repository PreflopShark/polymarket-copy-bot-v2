"""FastAPI application entry point."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from .routes.api import router as api_router
from .routes.websocket import router as ws_router
from .bot_manager import get_bot_manager, BotState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Polymarket Copy Bot Web App...")
    yield
    # Cleanup on shutdown
    logger.info("Shutting down...")
    manager = get_bot_manager()
    if manager.state == BotState.RUNNING:
        logger.info("Stopping bot...")
        await manager.stop()


# Create FastAPI app
app = FastAPI(
    title="Polymarket Copy Bot",
    description="Web interface for Polymarket copy trading bot",
    version="2.0.0",
    lifespan=lifespan
)

# Add CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(api_router, prefix="/api", tags=["API"])
app.include_router(ws_router, tags=["WebSocket"])

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_index():
    """Serve the main index.html."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Polymarket Copy Bot API", "docs": "/docs"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
