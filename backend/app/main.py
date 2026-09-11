"""
Application entrypoint.

Also serves the mandatory HTML/CSS(/JS) frontend directly from this same
FastAPI app (Jinja2 templates + static files), since the assignment does
not require a separate frontend stack -- this keeps deployment to a
single service.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes.documents import router as documents_router
from app.core.config import get_settings
from app.core.database import init_db
from app.core.logging import get_logger, setup_logging

setup_logging()
logger = get_logger("docintel.main")
settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent document extraction, financial validation and API platform.",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)

# Resolved relative to this file so the app works regardless of the
# process's current working directory (important on hosted platforms).
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(_FRONTEND_DIR / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s in %s environment", settings.APP_NAME, settings.ENVIRONMENT)
    init_db()


@app.get("/", tags=["frontend"])
def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/documents/{document_name}", tags=["frontend"])
def document_result_page(request: Request, document_name: str):
    return templates.TemplateResponse(
        "document_result.html", {"request": request, "document_name": document_name}
    )
