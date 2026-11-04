import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import settings
from app.database import init_db
from app.routers import tasks, vaults, settings as settings_router

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    init_db()
    yield

# Initialize FastAPI App
app = FastAPI(
    title=settings.APP_NAME,
    description="Hệ thống trích xuất & lưu trữ Media Facebook, Instagram, Threads, TikTok",
    version="1.0.0",
    lifespan=lifespan
)

# Ensure DB initialized
init_db()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(tasks.router)
app.include_router(vaults.router)
app.include_router(settings_router.router)

# Mount Static Folders
static_dir = settings.BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Mount Vault Directory for Media Streaming & Thumbnails
vault_dir = settings.VAULT_DIR
vault_dir.mkdir(parents=True, exist_ok=True)
app.mount("/vault", StaticFiles(directory=str(vault_dir)), name="vault")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = settings.BASE_DIR / "static" / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>Social Media Vault Backend is running!</h1><p>Please place index.html in the static folder.</p>")

@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}

if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
