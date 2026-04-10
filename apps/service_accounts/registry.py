"""Service account credential registry — the single entry point.

Every credential access in the application goes through get_credentials().
It enforces impersonation policy, validates scopes, logs access, and
dispatches to the appropriate credential provider.
"""
from __future__ import annotations

import importlib
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from .exceptions import ImpersonationDenied, InvalidScope, ServiceAccountNotFound
from .models import AccessLog, ImpersonationGrant, ServiceAccount

logger = logging.getLogger(__name__)


def _get_provider(credential_type: str):
    """Load and instantiate the credential provider for the given type."""
    sa_settings = getattr(settings, "SERVICE_ACCOUNTS", {})
    providers = sa_settings.get("PROVIDERS", {})
    dotted_path = providers.get(credential_type)
    if not dotted_path:
        raise ServiceAccountNotFound(
            f"No provider configured for credential type: {credential_type}"
        )
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)()


def _bootstrap_if_needed(name: str) -> ServiceAccount | None:
    """If the SA doesn't exist in DB but is configured for env bootstrap,
    create it from the environment variable."""
    sa_settings = getattr(settings, "SERVICE_ACCOUNTS", {})
    bootstrap = sa_settings.get("BOOTSTRAP_FROM_ENV", {})
    config = bootstrap.get(name)
    if not config:
        return None

    import os

    env_var = config["env_var"]
    raw = os.environ.get(env_var) or getattr(settings, env_var, "")
    if not raw:
        return None

    from .encryption import encrypt

    sa = ServiceAccount.objects.create(
        name=name,
        credential_type=config["credential_type"],
        credential_encrypted=encrypt(raw),
        default_scopes=config.get("default_scopes", []),
        description=f"Auto-bootstrapped from env var {env_var}",
    )
    logger.info("Bootstrapped service account %r from env var %s", name, env_var)
    return sa


def get_credentials(
    name: str,
    *,
    on_behalf_of: str | None = None,
    scopes: list[str] | None = None,
    context: dict | None = None,
) -> Any:
    """Return provider-specific credentials for the named service account.

    Args:
        name: The ServiceAccount.name to look up.
        on_behalf_of: If provided, impersonate this subject. A matching,
            active ImpersonationGrant must exist or ImpersonationDenied is raised.
        scopes: Override scopes (must be a subset of the SA's default_scopes
            or the grant's scopes). Defaults to the SA's default_scopes.
        context: Caller-provided metadata written to the AccessLog row.

    Returns:
        Provider-specific credential object.

    Raises:
        ServiceAccountNotFound: SA doesn't exist or is inactive.
        ImpersonationDenied: on_behalf_of provided but no valid grant matches.
        InvalidScope: Requested scopes exceed allowed scopes.
    """
    try:
        sa = ServiceAccount.objects.get(name=name, is_active=True)
    except ServiceAccount.DoesNotExist as exc:
        sa = _bootstrap_if_needed(name)
        if sa is None:
            raise ServiceAccountNotFound(
                f"Service account {name!r} not found or inactive"
            ) from exc

    effective_scopes = scopes if scopes is not None else list(sa.default_scopes)

    # Validate scopes against SA defaults
    allowed = set(sa.default_scopes)
    if not set(effective_scopes).issubset(allowed):
        excess = set(effective_scopes) - allowed
        raise InvalidScope(
            f"Scopes {excess} exceed allowed scopes {allowed} for SA {name!r}"
        )

    if on_behalf_of:
        # Find a matching, active grant
        now = timezone.now()
        grants = ImpersonationGrant.objects.filter(
            service_account=sa,
            revoked_at__isnull=True,
        )
        matched_grant = None
        for grant in grants:
            if grant.expires_at and grant.expires_at < now:
                continue
            if grant.matches(on_behalf_of):
                matched_grant = grant
                break

        if matched_grant is None:
            raise ImpersonationDenied(
                f"No valid impersonation grant for {on_behalf_of!r} on SA {name!r}"
            )

        # If caller didn't specify scopes, default to the grant's scopes
        # (the grant is always narrower than or equal to the SA's default_scopes).
        # If caller did specify scopes, validate they don't exceed the grant.
        grant_allowed = set(matched_grant.scopes)
        if scopes is None and grant_allowed:
            effective_scopes = list(matched_grant.scopes)
        elif grant_allowed and not set(effective_scopes).issubset(grant_allowed):
            excess = set(effective_scopes) - grant_allowed
            raise InvalidScope(
                f"Scopes {excess} exceed grant-allowed scopes {grant_allowed}"
            )

        AccessLog.objects.create(
            service_account=sa,
            action="impersonation",
            subject=on_behalf_of,
            scopes_used=effective_scopes,
            context=context or {},
        )
    else:
        AccessLog.objects.create(
            service_account=sa,
            action="direct_access",
            scopes_used=effective_scopes,
            context=context or {},
        )

    provider = _get_provider(sa.credential_type)
    return provider.get_credentials(
        sa.credential_json, subject=on_behalf_of, scopes=effective_scopes,
    )
