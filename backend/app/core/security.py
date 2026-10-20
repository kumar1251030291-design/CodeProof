"""Strict Supabase access-token verification using project signing keys."""

from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

from app.core.config import settings

ASYMMETRIC_ALGORITHMS = frozenset({"ES256", "RS256", "EdDSA"})


class InvalidAccessToken(Exception):
    """The token is malformed, untrusted, expired, or has invalid claims."""


class AuthenticationConfigurationError(Exception):
    """The server does not have the configuration needed to verify this token."""


class SigningKeyUnavailable(Exception):
    """The signing-key service could not be reached to verify a token."""


@lru_cache(maxsize=8)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    """Cache each project's JWKS client; PyJWT caches the fetched key set too."""
    return PyJWKClient(
        f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_jwk_set=True,
        lifespan=300,
        timeout=5,
    )


def authentication_diagnostic() -> dict[str, Any]:
    """Return non-secret auth readiness and cached public JWKS metadata status."""
    supabase_url = (settings.supabase_url or "").strip().rstrip("/")
    audience_configured = bool(settings.supabase_jwt_audience.strip())
    jwks_reachable = False
    jwks_algorithms: list[str] = []
    jwks_usable = False

    if supabase_url:
        try:
            keys = _jwks_client(supabase_url).get_signing_keys()
            jwks_reachable = True
            jwks_algorithms = sorted({
                key.algorithm_name for key in keys
                if key.algorithm_name in ASYMMETRIC_ALGORITHMS
            })
            jwks_usable = bool(jwks_algorithms)
        except (PyJWKClientConnectionError, PyJWKClientError, ValueError):
            # Keep details private; never return URLs, key IDs, or key material.
            pass

    hs256_configured = bool(settings.supabase_jwt_secret)
    configured = bool(supabase_url) and audience_configured
    return {
        "status": "ready" if configured and (hs256_configured or jwks_usable) else "not_ready",
        "project_url_configured": bool(supabase_url),
        "audience_configured": audience_configured,
        "legacy_hs256_secret_configured": hs256_configured,
        "jwks_reachable": jwks_reachable,
        "jwks_supported_algorithms": jwks_algorithms,
    }


def verify_supabase_access_token(token: str) -> dict[str, Any]:
    """Verify signature and standard Supabase access-token claims.

    Asymmetric signing keys are resolved through the project's cached JWKS.
    Legacy HS256 is accepted only when a backend-only JWT secret is configured.
    The untrusted ``alg`` header is used only to select between these fixed,
    separately configured verification paths; it never defines an allow-list.
    """
    supabase_url = (settings.supabase_url or "").strip().rstrip("/")
    if not supabase_url:
        raise AuthenticationConfigurationError from None

    try:
        parsed_url = urlsplit(supabase_url)
        hostname = parsed_url.hostname
    except ValueError:
        raise AuthenticationConfigurationError from None
    local_host = hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        parsed_url.scheme not in ({"https", "http"} if local_host else {"https"})
        or not hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.path not in {"", "/"}
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise AuthenticationConfigurationError from None
    supabase_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    issuer = f"{supabase_url}/auth/v1"
    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError:
        raise InvalidAccessToken from None

    algorithm = header.get("alg")
    if algorithm == "HS256":
        secret = settings.supabase_jwt_secret
        if not secret:
            raise AuthenticationConfigurationError from None
        key: Any = secret
    elif algorithm in ASYMMETRIC_ALGORITHMS:
        try:
            signing_key = _jwks_client(supabase_url).get_signing_key_from_jwt(token)
        except PyJWKClientConnectionError:
            raise SigningKeyUnavailable from None
        except PyJWKClientError:
            raise InvalidAccessToken from None
        if signing_key.algorithm_name != algorithm:
            raise InvalidAccessToken from None
        key = signing_key.key
    else:
        raise InvalidAccessToken from None

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=[algorithm],
            audience=settings.supabase_jwt_audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub", "aud"]},
        )
    except InvalidTokenError:
        raise InvalidAccessToken from None

    subject = claims.get("sub")
    try:
        UUID(subject)
    except (ValueError, TypeError, AttributeError):
        raise InvalidAccessToken from None
    return claims
