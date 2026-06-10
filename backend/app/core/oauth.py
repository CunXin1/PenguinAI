"""OAuth 2.0 / OpenID Connect for Google + Apple "Sign in with".

Design notes
------------
* **Stateless.** CSRF + nonce travel in a signed ``state`` JWT (see
  ``security.create_oauth_state_token``), so there is no server session or Redis
  entry to lose between the authorize redirect and the callback. This also makes
  Apple's cross-site ``form_post`` callback work, where a SameSite cookie would
  not be sent.
* **No hand-rolled crypto.** id_token signatures (Google RS256, Apple ES256) are
  verified by ``python-jose`` against each provider's published JWKS, and Apple's
  ES256 client-secret JWT is signed by jose too. We only fetch/cache the JWKS and
  match the ``kid``.

Endpoints and behaviour follow Google's OIDC docs and Apple's "Sign in with Apple".
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
from jose import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)


class OAuthError(Exception):
    """Any failure in the OAuth round-trip (config, network, or token validation)."""


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    jwks_url: str
    issuers: tuple[str, ...]  # acceptable `iss` values (Google publishes two)
    scopes: str
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


GOOGLE = Provider(
    name="google",
    authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    jwks_url="https://www.googleapis.com/oauth2/v3/certs",
    issuers=("https://accounts.google.com", "accounts.google.com"),
    scopes="openid email profile",
    extra_authorize_params={"access_type": "online", "prompt": "select_account"},
)

APPLE = Provider(
    name="apple",
    authorize_url="https://appleid.apple.com/auth/authorize",
    token_url="https://appleid.apple.com/auth/token",
    jwks_url="https://appleid.apple.com/auth/keys",
    issuers=("https://appleid.apple.com",),
    scopes="name email",
    # Apple requires form_post when name/email scopes are requested; it then
    # POSTs the callback (and the one-time `user` payload) instead of a GET.
    extra_authorize_params={"response_mode": "form_post"},
)

_PROVIDERS: dict[str, Provider] = {GOOGLE.name: GOOGLE, APPLE.name: APPLE}


def get_provider(name: str) -> Provider | None:
    return _PROVIDERS.get(name)


def client_id(provider: Provider) -> str:
    return settings.GOOGLE_CLIENT_ID if provider.name == "google" else settings.APPLE_CLIENT_ID


def is_configured(provider: Provider) -> bool:
    if provider.name == "google":
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    return bool(
        settings.APPLE_CLIENT_ID
        and settings.APPLE_TEAM_ID
        and settings.APPLE_KEY_ID
        and settings.APPLE_PRIVATE_KEY
    )


def redirect_uri(provider: Provider) -> str:
    """Must match the URI registered in the provider console *exactly*."""
    return f"{settings.OAUTH_REDIRECT_BASE.rstrip('/')}/api/auth/oauth/{provider.name}/callback"


def _apple_client_secret() -> str:
    """Apple's client secret is a short-lived ES256 JWT signed with the .p8 key."""
    now = int(time.time())
    payload = {
        "iss": settings.APPLE_TEAM_ID,
        "iat": now,
        "exp": now + 1800,  # Apple allows up to 6 months; short-lived is fine here
        "aud": "https://appleid.apple.com",
        "sub": settings.APPLE_CLIENT_ID,
    }
    return jwt.encode(
        payload,
        settings.APPLE_PRIVATE_KEY,
        algorithm="ES256",
        headers={"kid": settings.APPLE_KEY_ID},
    )


def _client_secret(provider: Provider) -> str:
    return settings.GOOGLE_CLIENT_SECRET if provider.name == "google" else _apple_client_secret()


def build_authorize_url(provider: Provider, state: str, nonce: str) -> str:
    params = {
        "client_id": client_id(provider),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": provider.scopes,
        "state": state,
        "nonce": nonce,
        **provider.extra_authorize_params,
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


async def exchange_code(provider: Provider, code: str) -> dict:
    """Swap an authorization code for tokens (the id_token carries the identity)."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
        "client_id": client_id(provider),
        "client_secret": _client_secret(provider),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            provider.token_url, data=data, headers={"Accept": "application/json"}
        )
    if resp.status_code != 200:
        raise OAuthError(f"token exchange failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


# ── JWKS cache (public keys used to verify id_token signatures) ──────────────
_jwks_cache: dict[str, tuple[float, list[dict]]] = {}
_JWKS_TTL = 3600.0


async def _fetch_jwks(provider: Provider) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(provider.jwks_url)
    resp.raise_for_status()
    return resp.json().get("keys", [])


async def _signing_key(provider: Provider, kid: str | None) -> dict:
    """Return the JWK matching `kid`, refreshing the cache once on a miss (rotation)."""
    now = time.time()
    cached = _jwks_cache.get(provider.name)
    if cached and cached[0] > now:
        for key in cached[1]:
            if key.get("kid") == kid:
                return key
    keys = await _fetch_jwks(provider)
    _jwks_cache[provider.name] = (now + _JWKS_TTL, keys)
    for key in keys:
        if key.get("kid") == kid:
            return key
    raise OAuthError(f"no matching signing key for kid={kid}")


async def verify_id_token(provider: Provider, id_token: str, nonce: str) -> dict:
    """Verify signature, audience, expiry, issuer and nonce; return the claims."""
    try:
        header = jwt.get_unverified_header(id_token)
        key = await _signing_key(provider, header.get("kid"))
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=client_id(provider),
            options={"verify_at_hash": False},  # no access_token passed → skip at_hash
        )
    except OAuthError:
        raise
    except Exception as exc:  # jose raises a variety of JWT/JWK errors
        raise OAuthError(f"id_token validation failed: {exc}") from exc

    if claims.get("iss") not in provider.issuers:
        raise OAuthError(f"unexpected issuer: {claims.get('iss')!r}")
    if nonce and claims.get("nonce") != nonce:
        raise OAuthError("nonce mismatch")
    return claims
