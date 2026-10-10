"""FastAPI application entry point."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.activity import router as activity_router
from app.api.auth import enforce_can_edit, router as auth_router
from app.api.bom import router as bom_router
from app.api.crud import routers as crud_routers
from app.api.dashboard import router as dashboard_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.metrics import router as metrics_router
from app.api.orders_api import router as orders_router
from app.api.reports import router as reports_router
from app.api.stock import router as stock_router
from app.api.transactions import (
    expense_router,
    inventory_router,
    transfer_router,
    work_router,
)
from app.config import settings

# `enforce_can_edit` runs before every request and rejects writes from
# read-only accounts, so all current and future write endpoints are covered
# without touching each one.
app = FastAPI(title=settings.app_name, dependencies=[Depends(enforce_can_edit)])

app.include_router(health_router)
app.include_router(auth_router)
for _router in crud_routers:
    app.include_router(_router)
app.include_router(bom_router)
app.include_router(activity_router)
app.include_router(stock_router)
app.include_router(orders_router)
app.include_router(expense_router)
app.include_router(work_router)
app.include_router(inventory_router)
app.include_router(transfer_router)
app.include_router(dashboard_router)
app.include_router(metrics_router)
app.include_router(reports_router)
app.include_router(imports_router)


# ---------------------------------------------------------------------------
# Serve the compiled React SPA (frontend/dist) from the same origin as the API.
# Same-origin means the session cookie just works with no CORS setup. In
# production the Docker image builds the SPA into this folder; in local dev the
# folder is usually absent and you run Vite separately, so we fall back to a
# small JSON banner at "/".
# ---------------------------------------------------------------------------
_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


if (_FRONTEND_DIST / "index.html").is_file():
    # Hashed build assets (JS/CSS/images) live under /assets.
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    _INDEX = _FRONTEND_DIST / "index.html"

    @app.get("/", include_in_schema=False)
    def spa_root() -> FileResponse:
        return FileResponse(_INDEX)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve a real static file if it exists, else index.html.

        This lets client-side routes (react-router deep links / refresh) resolve
        to the SPA. API routes are registered above and take precedence, so they
        are never shadowed by this catch-all.
        """
        candidate = _FRONTEND_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_INDEX)
else:  # Local dev without a build present.

    @app.get("/")
    def root() -> dict:
        return {"app": settings.app_name, "docs": "/docs"}
