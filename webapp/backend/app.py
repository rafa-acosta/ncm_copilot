"""FastAPI app factory for the NCM Copilot web frontend.

This module owns exactly two things: wiring the route modules together, and
translating the service layer's own exception types into clean HTTP
responses. No compliance/config/golden-config logic lives here or anywhere
under webapp/backend/routes/ - see webapp/backend/services/*.py, each of
which wraps one existing top-level module (see documentation/WEBAPP.md).
"""

from __future__ import annotations

import traceback
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from webapp.backend.routes import analysis, briefings, configs, dashboard, golden, reports, settings
from webapp.backend.services.analysis_service import AnalysisError
from webapp.backend.services.briefings_service import BriefingError
from webapp.backend.services.dashboard_service import DashboardError
from webapp.backend.services.golden_service import ProfileNotFound, ProfileValidationError
from webapp.backend.services.llm_engine_service import EngineError
from webapp.backend.services.reports_service import ReportError

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

# (exception type, http status) - only for exceptions whose own str(exc) is
# already safe to show a client (see the dedicated FileNotFoundError handler
# below for the one built-in exception whose message is NOT safe: it embeds
# the absolute server-side path).
_KNOWN_ERRORS: list[tuple[type[Exception], int]] = [
    (ProfileNotFound, 404),
    (ProfileValidationError, 422),
    (AnalysisError, 400),
    (BriefingError, 400),
    (ReportError, 400),
    (DashboardError, 400),
    (EngineError, 409),
    (ValueError, 400),  # e.g. resolve_within()'s path-escape guard - message only echoes the attempted relative parts
]


def create_app() -> FastAPI:
    app = FastAPI(title="NCM Copilot", version="1.0.0")

    for router in (configs.router, golden.router, analysis.router, briefings.router, reports.router, dashboard.router, settings.router):
        app.include_router(router)

    def _error_response(status_code: int, detail: str, technical: str) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": detail, "technical": technical})

    for exc_type, status_code in _KNOWN_ERRORS:
        def _make_handler(code: int):
            async def _handler(request: Request, exc: Exception) -> JSONResponse:
                message = str(exc) or exc.__class__.__name__
                return _error_response(code, message, f"{exc.__class__.__name__}: {exc}")

            return _handler

        app.add_exception_handler(exc_type, _make_handler(status_code))

    @app.exception_handler(FileNotFoundError)
    async def _file_not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
        # str(exc) embeds the absolute server-side path (e.g. "[Errno 2] No
        # such file or directory: '/home/.../webapp/data/runs/x'") - never
        # forward that to the client, in either field (see security.py's
        # own "never expose local filesystem paths" rule).
        return _error_response(404, "The requested item was not found.", "FileNotFoundError")

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # Never leak a raw traceback to the client - it's printed server-side
        # for diagnosis, and only the exception type/message reach the UI's
        # expandable "technical details" panel.
        traceback.print_exc()
        return _error_response(500, "An unexpected error occurred. Please try again.", f"{exc.__class__.__name__}: {exc}")

    # Static frontend - served from the same origin as the API, so the
    # browser never needs CORS at all. Routing is hash-based (#/golden-config
    # etc.) - the fragment never reaches the server, so every real request
    # this app sees is just "/" plus /api/* and /assets/*; no SPA path
    # fallback is needed for deep links to survive a hard refresh.
    if FRONTEND_DIR.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend-assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(FRONTEND_DIR / "index.html")

    return app


app = create_app()
