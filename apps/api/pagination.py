"""Offset/limit pagination shared across v2 list endpoints.

Pydantic generic — every list endpoint declares its response as
`Page[ItemSchema]` so the OpenAPI schema knows the item type.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)


def paginate(items: Sequence[T], *, offset: int, limit: int) -> Page[T]:
    total = len(items)
    sliced = list(items[offset : offset + limit])
    return Page(items=sliced, total=total, offset=offset, limit=limit)
