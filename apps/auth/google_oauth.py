"""Google sign-in protocol: OIDC authorization code + PKCE.

Only the protocol lives here — building the authorize URL, redeeming the code,
and *verifying* the ID token. What a verified identity is allowed to do
(admission, linking, the session) is `apps/auth/identity.py`, shared with the
other sign-in methods.

Why hand-rolled (httpx + PyJWT) rather than authlib: ace-web already runs the
Connect flow this way, PyJWT[crypto] is already a dependency, and the whole
Google surface is ~100 lines. django-allauth stays out, as CLAUDE.md records.

Everything the OIDC spec asks of a relying party is checked, not trusted to
the TLS channel: state (in the view), PKCE S256, and on the ID token the
RS256 signature against Google's JWKS, `iss`, `aud`, `exp`, `nonce`, and
`email_verified`.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from django.conf import settings
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

_jwks_client: PyJWKClient | None = None


class GoogleAuthError(Exception):
    """A Google sign-in failed. The message is safe to show the person."""


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


def is_configured() -> bool:
    return bool(settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET)


def new_flow() -> dict[str, str]:
    """Fresh single-use secrets for one sign-in attempt (kept in the session)."""
    return {
        "state": secrets.token_urlsafe(32),
        "nonce": secrets.token_urlsafe(32),
        "verifier": secrets.token_urlsafe(64),
    }


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorize_url(flow: dict[str, str], redirect_uri: str) -> str:
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": _challenge(flow["verifier"]),
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, verifier: str, redirect_uri: str) -> str:
    """Redeem the authorization code; return the raw ID token."""
    try:
        resp = httpx.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "code_verifier": verifier,
            },
            timeout=10,
        )
        resp.raise_for_status()
        id_token = resp.json().get("id_token")
    except httpx.HTTPStatusError as exc:
        logger.error("Google token exchange failed: %s %s", exc.response.status_code,
                     exc.response.text[:300])
        raise GoogleAuthError("Google rejected the sign-in. Please try again.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("Google token exchange unavailable: %s", exc)
        raise GoogleAuthError("Google is unavailable right now. Please try again later.") from exc
    if not id_token:
        raise GoogleAuthError("Google did not return an identity. Please try again.")
    return id_token


def _signing_key(id_token: str):
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client.get_signing_key_from_jwt(id_token).key


def verify_id_token(id_token: str, nonce: str) -> GoogleIdentity:
    """Validate the ID token and return the identity it asserts."""
    try:
        claims = jwt.decode(
            id_token,
            _signing_key(id_token),
            algorithms=["RS256"],
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
            issuer=list(ISSUERS),
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("Google ID token rejected: %s", exc)
        raise GoogleAuthError("Could not verify your Google sign-in. Please try again.") from exc

    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        logger.warning("Google ID token nonce mismatch")
        raise GoogleAuthError("Could not verify your Google sign-in. Please try again.")

    email = (claims.get("email") or "").strip().lower()
    # Google sends a bool; tolerate the string form some libraries produce.
    verified = claims.get("email_verified") in (True, "true")
    if not email or not verified:
        raise GoogleAuthError(
            "Google has not verified that email address, so it cannot be used to sign in."
        )
    return GoogleIdentity(sub=str(claims["sub"]), email=email, name=claims.get("name") or "")
