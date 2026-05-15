from apps.api.pagination import Page, paginate


def test_paginate_returns_page_with_metadata():
    items = list(range(95))
    page = paginate(items, offset=20, limit=25)
    assert isinstance(page, Page)
    assert page.items == list(range(20, 45))
    assert page.total == 95
    assert page.offset == 20
    assert page.limit == 25


def test_paginate_handles_overflow_gracefully():
    items = list(range(10))
    page = paginate(items, offset=50, limit=25)
    assert page.items == []
    assert page.total == 10


def test_paginate_defaults():
    items = list(range(5))
    page = paginate(items, offset=0, limit=100)
    assert page.items == items
    assert page.total == 5
