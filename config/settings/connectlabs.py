"""
Django settings for ace-web deployed to the connect-labs AWS environment.

Inherits production security settings but configures for:
- ALB TLS termination (no SSL redirect)
- /ace/ path prefix (FORCE_SCRIPT_NAME)
- tenant-unique session cookie name (avoids collisions with scout)
"""
from .production import *  # noqa: F401, F403

# ALB terminates TLS, so don't redirect HTTP -> HTTPS at Django level.
SECURE_SSL_REDIRECT = False

# ace-web is served under /ace/ path prefix on the ALB.
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
