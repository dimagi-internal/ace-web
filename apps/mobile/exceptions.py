"""Exceptions raised by the EmulatorController and SSM transport."""


class MobileError(Exception):
    """Base for mobile-runner exceptions. `code` lands in the API envelope."""

    code = "mobile-error"
    http_status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotConfigured(MobileError):
    code = "not-configured"
    http_status = 503


class SingletonBusy(MobileError):
    code = "singleton-busy"
    http_status = 503

    def __init__(self, owner: str):
        super().__init__(f"another caller holds the mobile-runner lock: {owner}")
        self.owner = owner


class EmulatorBootTimeout(MobileError):
    code = "boot-timeout"
    http_status = 504


class EmulatorNotReady(MobileError):
    """Raised when ensure_running finds the ready-marker but the
    emulator is not actually visible to adb. Indicates the marker is
    stale or the emulator died after registration. Carries the
    diagnostic snapshot collected at the moment of failure so callers
    don't have to make a second round-trip to find out why."""

    code = "emulator-not-ready"
    http_status = 503

    def __init__(self, message: str, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class SSMTimeout(MobileError):
    code = "ssm-timeout"
    http_status = 504


class SSMFailure(MobileError):
    code = "ssm-failure"
    http_status = 502
