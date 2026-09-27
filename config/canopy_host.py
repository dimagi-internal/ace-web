"""``CANOPY_HOST`` — the canopy SDK's one setting, derived from ace-web's own.

The SDK's Django integration (``canopy_sdk.django``) reads a ``CANOPY_HOST``
mapping. ace-web already configures canopy through flat ``CANOPY_*`` settings
(and its tests override them one at a time), so rather than keep a second copy
that ``override_settings(CANOPY_SIGNING_KEY=...)`` would silently miss, this
mapping is computed FROM the flat settings every time it is read. One source of
truth, and the SDK sees exactly what the rest of ace-web sees.

Imported by ``config/settings/base.py``, so nothing here may touch the ORM or
import an app at module level.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping


def _retired_keys(raw: str) -> tuple[str, ...]:
    """The retired public halves from ``CANOPY_RETIRED_PUBLIC_KEYS`` (pipe-
    separated PEMs), keeping only the ones that load.

    Skipping, not raising: a malformed retired key must never hide the LIVE one
    from the JWKS — that would refuse every assertion, not just old ones.
    """
    from cryptography.hazmat.primitives import serialization

    out = []
    for pem in (p.strip() for p in (raw or "").split("|")):
        if not pem:
            continue
        try:
            serialization.load_pem_public_key(pem.encode())
        except Exception:  # noqa: BLE001 - see docstring
            continue
        out.append(pem)
    return tuple(out)


class CanopyHostSettings(Mapping):
    """A read-only, always-current view of ace-web's canopy settings in the
    shape ``canopy_sdk.django.conf`` expects."""

    def _values(self) -> dict:
        from django.conf import settings as s

        public = (s.ACE_PUBLIC_BASE_URL or "").rstrip("/")
        return {
            # --- the arrival: the visitor assertion (unchanged behaviour) ---------
            "SIGNING_KEY": s.CANOPY_SIGNING_KEY,
            "CANOPY_BASE_URL": s.CANOPY_BASE_URL,
            "APP_NAME": s.CANOPY_APP_NAME,
            "AGENT_SLUG": s.CANOPY_AGENT_SLUG,
            "CANOPY_AUDIENCE": s.CANOPY_ASSERTION_AUDIENCE,
            "RETIRED_KEYS": _retired_keys(s.CANOPY_RETIRED_PUBLIC_KEYS),
            # --- the host grant: OFF until CANOPY_CLIENT_ID is set ----------------
            # The SDK turns the grant on only when all four are present; the last
            # three default from ace-web's public URL, so CLIENT_ID is the switch.
            "CLIENT_ID": s.CANOPY_CLIENT_ID,
            "ISSUER": s.CANOPY_GRANT_ISSUER or public,
            "RESOURCE": s.CANOPY_GRANT_RESOURCE or (f"{public}/api/mcp/" if public else ""),
            "TOKEN_ENDPOINT": s.CANOPY_GRANT_TOKEN_ENDPOINT
            or (f"{public}/api/canopy/oauth/token" if public else ""),
            "SCOPE_TOOLS": _registry("SCOPE_TOOLS"),
            "PAGE_SCOPES": _registry("PAGE_SCOPES"),
            # ace-web's `sub` for a person is their lower-cased email (what the
            # visitor assertion has always carried), so "is this subject still
            # live" is asked by email, not by primary key (the SDK default).
            "SUBJECT_ACTIVE": "apps.canopy.grant.subject_active",
        }

    def __getitem__(self, key: str):
        return self._values()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values())

    def __len__(self) -> int:
        return len(self._values())


def _registry(name: str) -> dict:
    # The scope → tools and page → scopes registries are CODE, reviewed like
    # code (apps/canopy/grant.py), not environment.
    from apps.canopy import grant

    return {k: list(v) for k, v in getattr(grant, name).items()}
