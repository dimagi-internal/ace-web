"""
Django settings for ace-web deployed to the connect-labs AWS environment.

Inherits production security settings but configures for:
- ALB TLS termination (no SSL redirect)
- /ace/ path prefix (FORCE_SCRIPT_NAME)
- tenant-unique session cookie name (avoids collisions with scout)
"""
from .production import *  # noqa: F401, F403

# ALB terminates TLS at the edge; the internal ALB -> nginx -> Django hop
# is plain HTTP. Tell Django to trust the X-Forwarded-Proto header (set
# by the ALB and preserved by nginx) so that `request.scheme` returns
# "https" for real client traffic and `request.build_absolute_uri()`
# produces https:// URLs. Critical for OAuth: without this, the callback
# URL is built as `http://labs.connect.dimagi.com/...` and the Connect
# OAuth app rejects it with redirect_uri_mismatch because the registered
# URL is https://.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Don't redirect HTTP -> HTTPS at Django level — ALB handles it.
SECURE_SSL_REDIRECT = False

# ace-web is served under /ace/ path prefix on the ALB. The FORCE_SCRIPT_NAME
# setting itself is defined in base.py; we just override the default here.
FORCE_SCRIPT_NAME = env("FORCE_SCRIPT_NAME", default="/ace")  # noqa: F405

# Tenant-unique session cookie to avoid collisions with scout / connect-labs
# on the shared labs.connect.dimagi.com domain.
SESSION_COOKIE_NAME = "sessionid_ace"
CSRF_COOKIE_NAME = "csrftoken_ace"

# CSRF trusted origin for POSTs from the ALB-fronted hostname.
# Without this, Django 4+/5 rejects all POST requests (including admin form
# submissions) with a 403 because the Origin header doesn't match the host.
CSRF_TRUSTED_ORIGINS = ["https://labs.connect.dimagi.com"]

# Path-scoped cookies so session state doesn't travel on requests to other
# tenants (scout, connect-labs) on the same labs.connect.dimagi.com hostname.
SESSION_COOKIE_PATH = "/ace/"
CSRF_COOKIE_PATH = "/ace/"

# 2026-05-08: Drive Changes API + snapshot cache redesign.
# Spec: docs/specs/2026-05-08-opp-cache-redesign.md
# Plan: docs/plans/2026-05-08-opp-cache-redesign.md
# Smoke tested locally; 46x speedup on warm-200, 55x on 304.
# Force-disable via OPPS_USE_CHANGES_API=false on the ECS task if needed.
OPPS_USE_CHANGES_API = env.bool("OPPS_USE_CHANGES_API", default=True)  # noqa: F405
