r"""Regression: a slug with a trailing newline must not survive `SLUG_RE`.

Python's `re` module special-cases `$`: unlike most regex engines, it matches
not only at the true end of a string but also immediately before a single
trailing `\n`. So `SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")` — which
reads as "anchored start, anchored end" — actually accepts `"acme\n"`,
because `$` happily matches right before that trailing newline:

    >>> import re
    >>> bool(re.compile(r"^[a-z0-9][a-z0-9-]*$").match("acme\n"))
    True

ace-web validates the workspace slug charset ONLY at the API layer (there is
no model-level `RegexValidator`, unlike the sibling `canopy-web` deployment),
so `SLUG_RE` in `apps.workspaces.api` is the single guard for this tenancy
invariant. `create_workspace()` calls `SLUG_RE.match(slug)`, which has the
same trailing-newline quirk as `.search()` — the fix is to anchor with `\Z`
(true end of string, no exception) instead of `$`.

Note: `WorkspaceCreateIn.slug` (schemas.py) also carries a `pattern=` field
constraint, and `StrictModel` sets `str_strip_whitespace=True` — so a
`"acme\n"` submitted over real HTTP is stripped to the clean slug `"acme"`
before it would ever reach `SLUG_RE.match()`. That means `SLUG_RE`'s own
robustness matters for callers that bypass or don't go through that Pydantic
validation step (e.g. `WorkspaceCreateIn.model_construct(...)`, which skips
validators entirely) — which is exactly what
`test_create_workspace_rejects_a_slug_with_a_trailing_newline` below
exercises, mirroring how the defect was originally verified (a direct,
schema-bypassing construction).
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.api.errors import ProblemError
from apps.workspaces.api import SLUG_RE, create_workspace
from apps.workspaces.models import Workspace
from apps.workspaces.schemas import WorkspaceCreateIn

User = get_user_model()


def _user(email="owner@example.com"):
    return User.objects.create_user(email=email)


def _bypassed_body(slug: str, *, folder_id: str = "folder-x") -> WorkspaceCreateIn:
    """Build a `WorkspaceCreateIn` with `model_construct()`, which skips all
    Pydantic validation (including the `pattern=` check and whitespace
    stripping) — the schema-bypass analog of `Workspace.objects.create(...)`
    used to verify the sibling canopy-web defect directly against the ORM.
    """
    return WorkspaceCreateIn.model_construct(
        slug=slug, name="Acme", drive_root_folder_id=folder_id
    )


# --- SLUG_RE itself -------------------------------------------------------


@pytest.mark.parametrize("slug", ["acme\n", "acme\r", "ac\nme"])
def test_slug_re_rejects_newline_variants(slug):
    """`$` matches before a trailing newline in Python `re`, so the anchor
    must be `\\Z`, which has no such exception."""
    assert SLUG_RE.match(slug) is None


@pytest.mark.parametrize("slug", ["acme", "acme-eu", "a1"])
def test_slug_re_still_accepts_valid_slugs(slug):
    assert SLUG_RE.match(slug) is not None


# --- create_workspace() — the API-layer guard ------------------------------


@pytest.mark.django_db
def test_create_workspace_rejects_a_slug_with_a_trailing_newline():
    """The defect as filed: a slug ending in `\\n` must not create a
    workspace. `$` matches before a trailing newline in Python `re`, so
    `SLUG_RE` needs `\\Z`, not `$`."""
    user = _user()
    body = _bypassed_body("acme\n")
    with pytest.raises(ProblemError) as exc:
        create_workspace(user, body)
    assert exc.value.status_code == 400
    assert not Workspace.objects.filter(slug="acme\n").exists()


@pytest.mark.django_db
def test_create_workspace_rejects_a_slug_with_a_trailing_carriage_return():
    user = _user()
    body = _bypassed_body("acme\r")
    with pytest.raises(ProblemError) as exc:
        create_workspace(user, body)
    assert exc.value.status_code == 400
    assert not Workspace.objects.filter(slug="acme\r").exists()


@pytest.mark.django_db
def test_create_workspace_rejects_a_slug_with_an_embedded_newline():
    user = _user()
    body = _bypassed_body("ac\nme")
    with pytest.raises(ProblemError) as exc:
        create_workspace(user, body)
    assert exc.value.status_code == 400
    assert not Workspace.objects.filter(slug="ac\nme").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("slug", ["acme", "acme-eu", "a1"])
def test_create_workspace_still_accepts_valid_slugs(slug):
    user = _user()
    body = _bypassed_body(slug, folder_id=f"folder-{slug}")
    result = create_workspace(user, body)
    assert result["slug"] == slug
    assert Workspace.objects.filter(slug=slug).exists()
