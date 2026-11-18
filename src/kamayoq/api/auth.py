"""Bearer token check of the /v1 routes, and the GET /v1/me endpoint."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from kamayoq.oidc import (
    IdentityProviderError,
    InvalidTokenError,
    OidcVerifier,
    Principal,
)

NOT_CONFIGURED_DETAIL = "This server has no OIDC login."
"""Detail of the 401 answer when the server has no OIDC settings."""
IDENTITY_PROVIDER_DETAIL = "The OIDC identity provider is not available."
"""Detail of the 503 answer when the IdP gives no signing keys."""
PUBLIC_V1_PATHS = frozenset({"/v1/auth/config"})
"""Paths under /v1 that need no token. Each other /v1 path needs one."""

bearer_scheme = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


def _unauthorized(detail: str, challenge: str = "Bearer") -> HTTPException:
    """Return a 401 error with the bearer challenge."""
    return HTTPException(401, detail, headers={"WWW-Authenticate": challenge})


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    """Return the principal of the bearer token, and keep it in request.state.

    Raises:
        HTTPException: 401 if the server has no OIDC settings, or the token is
            missing or not valid. 503 if the IdP gives no signing keys.
    """
    verifier: OidcVerifier | None = request.app.state.oidc_verifier
    if verifier is None:
        raise _unauthorized(NOT_CONFIGURED_DETAIL)
    if credentials is None:
        raise _unauthorized("Not authenticated")
    try:
        principal = await verifier.verify(credentials.credentials)
    except InvalidTokenError as error:
        logger.info("The API refused a bearer token: %s", error)
        raise _unauthorized(
            "The token is not valid.", 'Bearer error="invalid_token"'
        ) from None
    except IdentityProviderError:
        raise HTTPException(503, IDENTITY_PROVIDER_DETAIL) from None
    request.state.principal = principal
    return principal


def build_protected_router() -> APIRouter:
    """Return the /v1 router whose routes each need a valid token."""
    protected = APIRouter(prefix="/v1", dependencies=[Depends(current_principal)])

    @protected.get("/me")
    async def me(request: Request) -> dict[str, object]:
        """Return the subject, the issuer, and the groups of the token."""
        principal: Principal = request.state.principal
        return {
            "subject": principal.subject,
            "issuer": principal.issuer,
            "groups": sorted(principal.groups),
        }

    return protected


def build_router() -> APIRouter:
    """Return the router with the /v1 routes."""
    router = APIRouter()
    router.include_router(build_protected_router())
    return router
