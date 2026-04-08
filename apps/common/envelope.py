"""Standard envelope for JSON API responses, adapted from canopy-web."""
from typing import Any


def success_response(data: Any) -> dict[str, Any]:
    return {"data": data, "error": None}


def error_response(message: str, code: str = "error") -> dict[str, Any]:
    return {"data": None, "error": {"code": code, "message": message}}
