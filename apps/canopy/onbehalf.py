"""Running a call as the person a canopy agent is answering.

The other half of `apps/canopy/client.py`. There, ace-web vouches for one of
its people so canopy knows who is talking to an agent. Here the direction
reverses: the agent, part-way through answering that person, needs something
out of ace-web — and today it reads it with ACE's own credentials, which can
see every workspace. Nothing in ace-web knows which of its users the answer is
for, so nothing can narrow the read to them.

Canopy signs a short statement saying exactly that (`apps/tokens/onbehalf.py`
in canopy-web), and this verifies it and hands back an ace-web token for that
person. From then on the agent's calls are ordinary authenticated ace-web
calls, made AS them: our existing per-user rules apply with nothing new to
teach them, and a prompt-injected or simply careless agent cannot read what
that person could not.

What makes it safe to accept:

* **Canopy's signature, fetched from canopy** (`jwks_url`), never a key pasted
  here — so canopy can rotate without ace-web changing, and a leak of what
  ace-web stores yields nothing that can mint one.
* **`iss` must be the canopy we talk to.** Any other canopy is a stranger.
* **`aud` must be US.** Without it, an assertion canopy minted for a different
  connected site could be replayed here to act as its subject.
* **`jti` is single-use** and `exp` is short, so a copy taken from a log is
  worth nothing a moment later.
* **The user must already exist.** This mints a token for somebody; it must
  never invent the somebody. An unknown subject is refused.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache

#: How long canopy's published keys are reused before refetching.
JWKS_CACHE_SECONDS = 600
#: A `jti` cannot be spent twice inside this window. Comfortably longer than
#: the 120s canopy allows an assertion to live, so "already used" outlives
#: "still valid" — the gap is what would otherwise let a replay through.
JTI_SECONDS = 900
#: How long the token we hand back lives. Long enough to answer somebody
#: without re-minting per call; short enough that a leaked one is a small
#: window rather than a standing grant.
TOKEN_TTL_SECONDS = 4 * 60 * 60

FETCH_TIMEOUT = 5
MAX_JWKS_BYTES = 64 * 1024


class OnBehalfError(Exception):
    """Why this assertion was not accepted. Safe to show a caller."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _canopy_issuer() -> str:
    """Who canopy calls itself. The same value ace-web addresses assertions TO,
    because there is one canopy and it has one name."""
    return (settings.CANOPY_ASSERTION_AUDIENCE
            or (settings.CANOPY_BASE_URL or "").rstrip("/"))


def jwks_url() -> str:
    return f"{(settings.CANOPY_BASE_URL or '').rstrip('/')}/api/tokens/on-behalf-of/jwks"


def _fetch_jwks() -> list[dict]:
    url = jwks_url()
    if not url.startswith("https://") and "127.0.0.1" not in url and "localhost" not in url:
        # Plaintext in production would let an intermediary swap the key and
        # forge every assertion. Local development is the one exception.
        raise OnBehalfError("keys_unreachable", "canopy's key URL must be https")
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
            body = resp.read(MAX_JWKS_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise OnBehalfError("keys_unreachable", f"could not read canopy's keys ({exc})") from exc
    if len(body) > MAX_JWKS_BYTES:
        raise OnBehalfError("keys_unreachable", "canopy's key document is implausibly large")
    try:
        keys = json.loads(body)["keys"]
        assert isinstance(keys, list)
    except Exception as exc:  # noqa: BLE001
        raise OnBehalfError("keys_unreachable", f"canopy did not return a JWKS ({exc})") from exc
    return [k for k in keys if isinstance(k, dict)]


def _keys(kid: str, *, force: bool = False) -> list:
    """Canopy's public keys, narrowed to `kid` when the assertion names one.

    An unseen `kid` means canopy rotated; that forces ONE refetch rather than
    refusing valid assertions until the cache expires.
    """
    from jwt import PyJWK

    cached = None if force else cache.get("canopy:jwks")
    if cached is None:
        cached = _fetch_jwks()
        cache.set("canopy:jwks", cached, JWKS_CACHE_SECONDS)
    entries = [k for k in cached if not kid or k.get("kid") == kid]
    if kid and not entries and not force:
        return _keys(kid, force=True)
    out = []
    for entry in entries:
        try:
            out.append(PyJWK.from_dict(entry).key)
        except Exception:  # noqa: BLE001 - one bad entry must not hide the rest
            continue
    return out


def subject_of(assertion: str) -> str:
    """The person canopy says its agent is answering, or raise.

    Returns the subject exactly as canopy stated it — for ace-web that is the
    address we ourselves asserted when we vouched for them, so it round-trips
    to the same person rather than needing a second mapping nobody maintains.
    """
    import jwt

    if not assertion or not isinstance(assertion, str):
        raise OnBehalfError("no_assertion", "no assertion was sent")
    try:
        kid = str((jwt.get_unverified_header(assertion) or {}).get("kid") or "")
    except Exception as exc:  # noqa: BLE001
        raise OnBehalfError("malformed", "that is not a readable assertion") from exc

    keys = _keys(kid)
    if not keys:
        raise OnBehalfError("keys_unreachable", "canopy published no key that could verify this")

    last: Exception | None = None
    claims = None
    for key in keys:
        try:
            claims = jwt.decode(
                assertion,
                key,
                # OURS, not the token's — the difference between a verifier and
                # a forgery oracle.
                algorithms=["EdDSA", "ES256", "RS256"],
                audience=settings.CANOPY_APP_NAME,
                issuer=_canopy_issuer(),
                leeway=30,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "jti"],
                         "verify_exp": True, "verify_aud": True, "verify_iss": True},
            )
            break
        except jwt.InvalidAudienceError as exc:
            raise OnBehalfError(
                "wrong_audience",
                "that assertion was minted for a different site",
            ) from exc
        except jwt.InvalidIssuerError as exc:
            raise OnBehalfError("wrong_issuer", "that assertion is not from our canopy") from exc
        except jwt.ExpiredSignatureError as exc:
            raise OnBehalfError("expired", "that assertion has expired") from exc
        except Exception as exc:  # noqa: BLE001 - try the next key
            last = exc
    if claims is None:
        raise OnBehalfError("bad_signature", f"no canopy key verifies this ({last})")

    jti = str(claims.get("jti") or "")
    if not jti:
        raise OnBehalfError("incomplete", "that assertion has no jti")
    # `add` only succeeds if the key is absent, which is what makes this a
    # spend rather than a check-then-set two callers can both pass.
    if not cache.add(f"canopy:obo-jti:{jti}", 1, JTI_SECONDS):
        raise OnBehalfError("replayed", "that assertion has already been used")

    subject = str(claims.get("sub") or "").strip().lower()
    if not subject:
        raise OnBehalfError("incomplete", "that assertion names nobody")
    return subject


def token_for(assertion: str) -> tuple[str, object]:
    """Verify `assertion` and mint a short-lived ace-web token for its subject.

    Never creates a user: this exists to let an agent act as somebody who
    already uses ace-web, and inventing the somebody would make a signature
    from canopy into an account factory.
    """
    from django.contrib.auth import get_user_model

    from apps.auth.models import PersonalToken

    email = subject_of(assertion)
    user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
    if user is None:
        raise OnBehalfError(
            "unknown_subject",
            "nobody with that address has an active ace-web account",
        )
    raw, token = PersonalToken.create_for_user(
        user=user, label="canopy agent, on behalf of this user",
        ttl_seconds=TOKEN_TTL_SECONDS,
    )
    return raw, token
