import logging
import os
import time
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from cre.auth import demo_enabled
from cre.db import engine
from cre.explorer import router as explorer
from cre.field_capture import router as field_capture
from cre.field_places import router as field_places
from cre.field_sites import router as field_sites
from cre.workflows.api import router as workflows


def make_app():
    app = FastAPI(title="CRE Intelligence", version="0.1.0")
    app.include_router(explorer)
    app.include_router(field_capture)
    app.include_router(field_sites)
    app.include_router(field_places)
    app.include_router(workflows)

    @app.middleware("http")
    async def trace(request: Request, call_next):
        start = time.perf_counter()
        request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        route = request.scope.get("route")
        logging.getLogger("uvicorn.error").info(
            "request_id=%s method=%s route=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            getattr(route, "path", "unknown"),
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response

    @app.get("/health/live")
    def live():
        return {"status": "live"}

    @app.get("/health/ready")
    def ready(response: Response):
        try:
            with engine().connect() as conn:
                checks = conn.execute(
                    text("""SELECT NOT (rolsuper OR rolbypassrls),
                  to_regclass('core.visible_parcel') IS NOT NULL,
                  to_regclass('core.exportable_screening_version') IS NOT NULL,
                  has_table_privilege(current_user,'core.visible_parcel','SELECT'),
                  has_table_privilege(current_user,'operations.workflow_job','INSERT') FROM pg_roles WHERE rolname=current_user""")
                ).one()
            if not all(checks):
                raise RuntimeError("Database not ready")
            if os.getenv("CRE_ENV") == "production":
                for key in (
                    "CRE_OIDC_ISSUER",
                    "CRE_OIDC_AUDIENCE",
                    "CRE_OIDC_JWKS_URL",
                    "CRE_S3_BUCKET",
                ):
                    if not os.getenv(key):
                        raise RuntimeError("Production configuration missing")
                if os.getenv("CRE_DEMO_MODE", "").lower() == "true":
                    raise RuntimeError("Demo mode configured on production")
        except (KeyError, SQLAlchemyError, RuntimeError):
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready", "demo": demo_enabled()}

    return app


app = make_app()
