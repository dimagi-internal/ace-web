# Connect OAuth: Getting the user's email via OIDC

## Problem

Connect's token introspection endpoint returns an empty `email` field for
HQ-linked accounts. The OIDC `/o/userinfo/` endpoint returns 401 without
the `openid` scope.

## Solution

Request `openid` in the OAuth scopes AND add `response_type=token` to the
token exchange POST. Without `response_type=token`, Connect's token endpoint
crashes (500) trying to generate a signed JWT ID token — the OAuth app
doesn't have OIDC signing keys configured.

```python
# In the authorize URL:
scope = "read openid"

# In the token exchange POST:
token_data = {
    "grant_type": "authorization_code",
    "code": code,
    "redirect_uri": callback_url,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "code_verifier": code_verifier,
    "response_type": "token",  # <-- prevents signed JWT crash
}
```

After the token exchange, `/o/userinfo/` returns the email:
```json
{"sub": "6299", "name": "", "email": "ace@dimagi-ai.com", "username": "ace"}
```

## Also fixed

- Post-login redirect must use `FORCE_SCRIPT_NAME + "/"` (not bare `/`)
  on shared ALB infrastructure, otherwise the redirect lands on a different
  tenant app.

## Source

Per Connect team guidance (Sarvesh's implementation). connect-labs has the
same pattern but had `openid` disabled in prod with a TODO.
