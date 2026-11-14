"""Liveness and readiness endpoints."""

import asyncio
import logging
import math
import time

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse

READINESS_CACHE_SECONDS = 1.0
"""Time that one readiness result answers each later call."""

logger = logging.getLogger(__name__)


class ReadinessCheck:
    """Check that Postgres answers, with one check at a time in each process."""

    def __init__(self, database_url: str, timeout: float) -> None:
        """Keep the URL and the time limit of one check."""
        self._database_url = database_url
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._checked_at = -math.inf
        self._ready = False

    async def is_ready(self) -> bool:
        """Return True if Postgres answered the last check."""
        async with self._lock:
            if time.monotonic() - self._checked_at >= READINESS_CACHE_SECONDS:
                self._ready = await self._check()
                self._checked_at = time.monotonic()
            return self._ready

    async def _check(self) -> bool:
        """Return True if Postgres answers SELECT 1 within the timeout."""
        try:
            async with asyncio.timeout(self._timeout):
                async with await psycopg.AsyncConnection.connect(
                    self._database_url,
                    connect_timeout=math.ceil(self._timeout),
                    autocommit=True,
                ) as connection:
                    await connection.execute("SELECT 1")
        except Exception as error:
            logger.warning("Postgres is not ready: %s: %s", type(error).__name__, error)
            return False
        return True


def build_router(check: ReadinessCheck) -> APIRouter:
    """Return the router with /healthz and /readyz."""
    router = APIRouter()

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Return ok while the process runs."""
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz() -> JSONResponse:
        """Return ok when Postgres answers, or 503."""
        if await check.is_ready():
            return JSONResponse({"status": "ok"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    return router
