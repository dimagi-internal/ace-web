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
