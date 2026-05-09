"""CLI authorize endpoint — gh-style loopback flow for minting a PersonalToken.

A local CLI (the ACE plugin's /ace:ace-web-pat-mint script) starts a
listener on 127.0.0.1:NNNN, then opens the operator's browser to
/auth/cli/authorize/?cb=http://127.0.0.1:NNNN/cb&state=<nonce>&label=<...>.

This view:
  - Requires the operator to be signed in (bounces through OAuth via
    @login_required + ?next=).
  - Validates the callback URL is a loopback HTTP target (rejecting
    anything that could leak the token to a remote host).
  - GET renders a one-click authorize page.
  - POST mints a PersonalToken bound to request.user, then 302 redirects
    to <cb>?token=<raw>&state=<state>. The local listener captures it.

Replaces the deprecated shared-secret /auth/e2e-login/ flow. PR pair:
  ace-web PR adds this endpoint (does not remove e2e-login)
  ACE plugin PR migrates upload-transcript + adds the mint command
  ace-web PR removes e2e-login after a soak period
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode, urlparse

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from .models import PersonalToken

logger = logging.getLogger(__name__)

ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_LABEL = "ace-cli"
MAX_LABEL_LEN = 64


def _validate_callback(cb: str) -> str | None:
    """Return cb if it is a safe loopback HTTP URL, else None.

    Rejects anything that could leak the token to a non-loopback host:
    non-http schemes, non-loopback hosts, embedded userinfo, privileged
    or absent ports.
    """
    if not cb:
        return None
    try:
        u = urlparse(cb)
    except ValueError:
        return None
    if u.scheme != "http":
        return None
    if u.hostname not in ALLOWED_LOOPBACK_HOSTS:
        return None
    if u.username or u.password:
        return None
    if u.port is None:
        return None
    if not (1024 <= u.port <= 65535):
        return None
    return cb


@login_required
@require_http_methods(["GET", "POST"])
def cli_authorize(request: HttpRequest) -> HttpResponse:
    """Mint a PersonalToken for request.user and redirect to a loopback CLI."""
    cb = _validate_callback(request.GET.get("cb", ""))
    state = (request.GET.get("state") or "").strip()
    label = (request.GET.get("label") or DEFAULT_LABEL).strip()[:MAX_LABEL_LEN] or DEFAULT_LABEL

    if not cb:
        return HttpResponseBadRequest("invalid or missing cb (must be http://127.0.0.1:NNNN/...)")
    if not state:
        return HttpResponseBadRequest("missing state")

    if request.method == "GET":
        return render(
            request,
            "auth/cli_authorize.html",
            {
                "label": label,
                "cb_host": urlparse(cb).netloc,
                # Re-emit the query params on the form's action so POST stays self-contained.
                "form_action": request.get_full_path(),
            },
        )

    raw, token = PersonalToken.create_for_user(user=request.user, label=label)
    logger.info(
        "cli_authorize: minted token for %s (label=%r, pk=%s, cb_host=%s)",
        request.user.email, label, token.pk, urlparse(cb).netloc,
    )
    qs = urlencode({"token": raw, "state": state})
    return HttpResponseRedirect(f"{cb}?{qs}")
