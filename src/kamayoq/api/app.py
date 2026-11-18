"""Factory of the kamayoq FastAPI app."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from urllib.parse import unquote

import httpx2
from fastapi import FastAPI

from kamayoq import plugins
from kamayoq.api import auth, health
from kamayoq.db.engine import create_db_engine, create_sessionmaker, sqlalchemy_url
from kamayoq.oidc import HTTP_TIMEOUT_SECONDS, OidcKeys, OidcVerifier
from kamayoq.secrets import build_secret_store, remember
from kamayoq.settings import Settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    """Return the API app for these settings.

    The app holds the plugin registry, one database engine, one session maker, the
    secret store, and the OIDC verifier in app.state. The verifier is None when the
    OIDC settings are not set. The app closes the engine and the IdP client when it
    stops. Log lines hide the database password.

    Raises:
        PluginError: If a plugin on the allowlist cannot load.
    """
    password = settings.database_url.hosts()[0]["password"]
    if password:
        for form in {password, unquote(password)}:
            remember(form, "the database password")
    registry = plugins.load_plugins(settings.plugins, plugins.PLUGIN_GROUPS)
    engine = create_db_engine(sqlalchemy_url(settings))
    issuer = settings.oidc_issuer
    audience = settings.oidc_audience
    idp_client: httpx2.AsyncClient | None = None
    verifier: OidcVerifier | None = None
    if issuer is not None and audience is not None:
        idp_client = httpx2.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        keys = OidcKeys(issuer, idp_client)
        verifier = OidcVerifier(keys, issuer, audience, settings.oidc_groups_claim)
    else:
        logger.warning("OIDC settings are not set, so each protected route returns 401")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        try:
            await engine.dispose()
        finally:
            if idp_client is not None:
                await idp_client.aclose()

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
    app.state.secrets = build_secret_store(settings)
    app.state.oidc_verifier = verifier
    check = health.ReadinessCheck(
        str(settings.database_url), settings.readiness_timeout
    )
    app.include_router(health.build_router(check))
    app.include_router(auth.build_router())
    return app
