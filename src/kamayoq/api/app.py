"""Factory of the kamayoq FastAPI app."""

from importlib.metadata import version

from fastapi import FastAPI

from kamayoq.api.health import ReadinessCheck, build_router
from kamayoq.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    """Return the API app for these settings."""
    docs = settings.api_docs
    app = FastAPI(
        title="kamayoq",
        version=version("kamayoq"),
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    check = ReadinessCheck(str(settings.database_url), settings.readiness_timeout)
    app.include_router(build_router(check))
    return app
