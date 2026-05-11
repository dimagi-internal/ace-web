# `apps/opps/access.py` — patch this, not `apps.opps.views.X`

The opps Workbench used to be a single 1,583-line `apps/opps/views.py`,
with private helpers `_resolve_workspace`, `_require_drive`,
`_resolve_ace_root_folder_id`, `_overlay_workspace_display_name`, and
`_snapshot_etag` defined at module level. Tests intercepted these via
`patch("apps.opps.views._resolve_ace_root_folder_id", ...)`.

After the 2026-05-10 split (PR #286), the views live across four files:

- `apps/opps/views.py` — read views + the GET/POST and GET/PATCH/DELETE
  dispatchers (`opp_collection`, `workbench`)
- `apps/opps/views_write.py` — create / fork / delete / patch / artifact-write
- `apps/opps/views_session.py` — `discuss`, `step_chats`, `opp_working_session`
- `apps/opps/views_summary.py` — public per-run summary (no auth)

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

`apps.opps.views._resolve_ace_root_folder_id` still exists as a backward
compatibility alias for older test files — it's a binding inside views.py
that points at `access.resolve_ace_root_folder_id`. Patching it works
**only** for views still living in `views.py`; views moved to
`views_write.py` / `views_session.py` / `views_summary.py` won't see the
patch and you'll get the original function's behavior with no error.

If a test seems to ignore your mock, the most likely cause is patching
`apps.opps.views._resolve_*` on a view that has migrated out of views.py.

## When you add a new opps view

- Use `from apps.opps import access` and call `access.X(...)` for any
  workspace / Drive resolution. **Don't** add local underscore aliases
  in the new file — it makes test patching ambiguous.
- If you add a new helper to `access.py`, make it a module-level
  function (not a method) so attribute-time lookup works.

## Exception: `views_summary.py`'s `public_opp_summary`

The public summary endpoint bypasses the standard auth gate
(`@permission_classes([AllowAny])`) and looks up the workspace from a
URL slug. It calls `get_drive_client` directly from
`apps.opps.drive_client`, not via `access.require_drive`. Tests for
this view patch `apps.opps.views_summary.get_drive_client`, not the
access module. See `apps/opps/tests/test_public_summary.py`.

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
