"""Factory of the kamayoq FastAPI app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from urllib.parse import unquote

from fastapi import FastAPI

from kamayoq import plugins
from kamayoq.api.health import ReadinessCheck, build_router
from kamayoq.db.engine import create_db_engine, create_sessionmaker, sqlalchemy_url
from kamayoq.secrets import remember
from kamayoq.settings import Settings


def create_app(settings: Settings) -> FastAPI:
    """Return the API app for these settings.

    The app holds the plugin registry, one database engine, and one session maker
    in app.state. It disposes of the engine when it stops. Log lines hide the
    database password.

    Raises:
        PluginError: If a plugin on the allowlist cannot load.
    """
    password = settings.database_url.hosts()[0]["password"]
    if password:
        remember(password, "the database password")
        if unquote(password) != password:
            remember(unquote(password), "the database password")
    registry = plugins.load_plugins(settings.plugins, plugins.PLUGIN_GROUPS)
    engine = create_db_engine(sqlalchemy_url(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    docs = settings.api_docs
    app = FastAPI(
        title="kamayoq",
        lifespan=lifespan,
        version=version("kamayoq"),
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.plugins = registry
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    check = ReadinessCheck(str(settings.database_url), settings.readiness_timeout)
    app.include_router(build_router(check))
    return app
