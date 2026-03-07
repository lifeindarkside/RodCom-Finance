import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from config import UPLOAD_DIR
from database import engine, Base
from bot import start_bot
from scheduler import start_scheduler

from routers.auth import router as auth_router, auth_page_router
from routers.file_uploads import router as uploads_router
from routers.transactions import router as transactions_router
from routers.collections import router as collections_router
from routers.users import router as users_router
from routers.dashboard import router as dashboard_router
from routers.admin import router as admin_router
from compliance import router as compliance_router

app = FastAPI(title="РодКом Финансы", docs_url="/api/docs")

os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(auth_router)
app.include_router(auth_page_router)
app.include_router(uploads_router)
app.include_router(transactions_router)
app.include_router(collections_router)
app.include_router(users_router)
app.include_router(dashboard_router)
app.include_router(admin_router)
app.include_router(compliance_router)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        try:
            await conn.execute(text("ALTER TABLE collections ADD COLUMN collection_type TEXT DEFAULT 'general'"))
            logging.info("Added collection_type column to collections table")
        except Exception:
            pass
    asyncio.create_task(start_bot())
    asyncio.create_task(start_scheduler())


@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")


@app.get("/{path:path}")
async def serve_spa(path: str):
    static_path = os.path.join("static", path)
    if os.path.isfile(static_path):
        return FileResponse(static_path)
    return FileResponse("static/index.html")
