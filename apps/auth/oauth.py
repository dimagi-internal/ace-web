"""
Connect OAuth Helper Functions.

Shared OAuth utilities for the ACE web OAuth flow.
"""

import logging

import httpx

logger = logging.getLogger(__name__)


def introspect_token(
    access_token: str, client_id: str, client_secret: str, production_url: str
) -> dict | None:
    """
    Introspect OAuth token to get user profile information.

    Calls the OAuth introspection endpoint to validate the token and retrieve
    user information including ID, username, and email.

    Args:
        access_token: OAuth Bearer token to introspect
        client_id: OAuth client ID
        client_secret: OAuth client secret (required for introspection)
        production_url: Base URL of production Connect instance

    Returns:
        Dict with user profile {'id', 'username', 'email', 'first_name', 'last_name'}
        or None if introspection fails or token is invalid.
    """
    try:
        introspect_response = httpx.post(
            f"{production_url}/o/introspect/",
            data={"token": access_token},
            auth=(client_id, client_secret),
            timeout=10,
        )

        if introspect_response.status_code != 200:
            logger.warning(
                f"Token introspection failed with status {introspect_response.status_code}"
            )
            return None

        introspect_data = introspect_response.json()

        if not introspect_data.get("active"):
            logger.warning("Token is not active")
            return None

        # Extract user profile from introspection response.
        # sub may contain the CommCareHQ username (e.g. mtheis@dimagi.com for Dimagi staff).
        # Use it as an email fallback if it looks like an email address.
        sub = introspect_data.get("sub", "")
        sub_email = sub if "@" in str(sub) else ""

        profile_data = {
            "id": introspect_data.get("user_id") or sub or 0,
            "username": introspect_data.get("username"),
            "email": introspect_data.get("email", "") or sub_email,
            "first_name": introspect_data.get("given_name", ""),
            "last_name": introspect_data.get("family_name", ""),
        }

        logger.info(f"Token introspection successful for user: {profile_data.get('username')}")
        return profile_data

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error during token introspection: {str(e)}")
        return None
    except Exception as e:
        logger.warning(f"Failed to introspect token: {str(e)}")
        return None


def fetch_userinfo(access_token: str, production_url: str) -> dict | None:
    """
    Fetch OIDC userinfo from Connect production.

    Calls /o/userinfo/ with the bearer token and returns the JSON response.
    Useful for getting a verified email when introspection doesn't include one.

    Args:
        access_token: OAuth Bearer token
        production_url: Base URL of production Connect instance

    Returns:
        Dict with OIDC userinfo (typically includes 'email', 'sub', etc.)
        or None if the request fails.
    """
    try:
        response = httpx.get(
            f"{production_url}/o/userinfo/",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )

        if response.status_code != 200:
            logger.warning(f"Userinfo request failed with status {response.status_code}")
            return None

        return response.json()

    except httpx.HTTPError as e:
        logger.warning(f"HTTP error fetching userinfo: {str(e)}")
        return None
    except Exception as e:
        logger.warning(f"Failed to fetch userinfo: {str(e)}")
        return None


def fetch_user_email(access_token: str, production_url: str) -> str | None:
    """Fetch the user's email from Connect's user API.

    Tries multiple Connect API endpoints to find the user's email.
    This is a fallback for when introspection and OIDC userinfo don't
    return an email (common for HQ-linked accounts without the openid scope).
    """
    endpoints = [
        "/api/users/me/",
        "/api/user/",
        "/users/api/me/",
    ]
    for endpoint in endpoints:
        try:
            response = httpx.get(
                f"{production_url}{endpoint}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
                follow_redirects=True,
            )
            if response.status_code == 200:
                data = response.json()
                email = data.get("email") or data.get("user", {}).get("email", "")
                if email:
                    logger.info(f"Got email from {endpoint}: {email}")
                    return email
                # Some Connect APIs return 'name' which may be the HQ username
                # (which is the email for HQ-linked accounts)
                name = data.get("name", "")
                if "@" in str(name):
                    logger.info(f"Got email from {endpoint} name field: {name}")
                    return name
                # Try following the 'url' field to get the full user resource
                user_url = data.get("url", "")
                if user_url:
                    try:
                        detail_resp = httpx.get(
                            user_url,
                            headers={"Authorization": f"Bearer {access_token}"},
                            timeout=10,
                            follow_redirects=True,
                        )
                        if detail_resp.status_code == 200:
                            detail = detail_resp.json()
                            detail_email = detail.get("email", "")
                            if detail_email:
                                logger.info(f"Got email from user detail URL: {detail_email}")
                                return detail_email
                            logger.info(f"User detail URL returned: {detail}")
                    except Exception as e:
                        logger.debug(f"Failed to fetch user detail URL: {e}")
                logger.info(
                    f"{endpoint} returned 200 but no email: {data}"
                )
        except Exception as e:
            logger.debug(f"Failed to fetch {endpoint}: {e}")
            continue
    return None
