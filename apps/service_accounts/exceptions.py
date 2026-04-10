"""Exceptions raised by the service accounts registry."""


class ServiceAccountNotFound(Exception):
    """The requested service account does not exist or is inactive."""


class ImpersonationDenied(Exception):
    """No valid impersonation grant exists for the requested subject."""


class InvalidScope(Exception):
    """Requested scopes exceed the allowed scopes for this SA or grant."""
