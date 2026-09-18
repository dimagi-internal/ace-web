# `apps/opps/access.py` — patch this, not `apps.opps.views.X`

The opps Workbench used to be a single 1,583-line `apps/opps/views.py`,
with private helpers `_resolve_workspace`, `_require_drive`,
`_resolve_ace_root_folder_id`, `_overlay_workspace_display_name`, and
`_snapshot_etag` defined at module level. Tests intercepted these via
`patch("apps.opps.views._resolve_ace_root_folder_id", ...)`.

The 2026-05-10 split (PR #286) broke that file into `views.py` /
`views_write.py` / `views_session.py` / `views_summary.py`; the API
modernization (PRs #345–#352) then replaced the DRF views with the Ninja
router in `apps/opps/api.py`, and `views.py`, `views_session.py` and
`views_summary.py` are all gone now. **Current callers of `access`:**
`apps/opps/api.py` (every workspace-scoped endpoint) and
`apps/opps/summary.py`. `views_write.py` survives but doesn't use it.

Every view calls the helpers as **module attributes on `apps.opps.access`**:

```python
ws, client, err = access.require_drive(request)
ace_folder_id = access.resolve_ace_root_folder_id(ws)
```

This is deliberate. Attribute lookup happens at call time, not at import
time, so a single `mock.patch("apps.opps.access.X")` intercepts every
caller — no matter which split file owns the view.

## When you write a new test that mocks Drive access

Patch on `apps.opps.access.*`:

```python
with patch("apps.opps.access.get_drive_client", lambda **kw: fake), \
     patch("apps.opps.access.resolve_ace_root_folder_id",
           lambda *a, **kw: fake.folder_id("ACE")):
    response = authed_client.get("/api/opps/...")
```

The old `apps.opps.views._resolve_*` aliases died with `views.py`. If a test
seems to ignore your mock, the most likely cause is patching a name bound in
the caller's module (`from apps.opps.access import X`) instead of the
attribute on `apps.opps.access`.

## When you add a new opps view

- Use `from apps.opps import access` and call `access.X(...)` for any
  workspace / Drive resolution. **Don't** add local underscore aliases
  in the new file — it makes test patching ambiguous.
- If you add a new helper to `access.py`, make it a module-level
  function (not a method) so attribute-time lookup works.

## Exception: the public (no-auth) endpoints

The public run summary and its write endpoints live on
`public_summary_router = Router(auth=None)` in `apps/opps/api.py` and look
up the workspace from a URL slug. They lazily import `get_drive_client`
from `apps.opps.drive_client` rather than going through
`access.require_drive`, so their tests patch
`apps.opps.drive_client.get_drive_client`, not the access module.

## Why this matters

Before the split, `apps/activity/views.py` reached into private symbols
on `apps.opps.views` (`_require_drive`, `_resolve_workspace`,
`_resolve_ace_root_folder_id`). That's the smell that triggered the
extraction: private symbols were being treated as a public API across
app boundaries. `access.py` makes the public surface explicit and the
import legal.

A future split (e.g. extracting `views_read.py`) will not re-trigger
this trap as long as the new module sticks to `access.X` attribute
lookup. Don't reintroduce module-level aliases.
