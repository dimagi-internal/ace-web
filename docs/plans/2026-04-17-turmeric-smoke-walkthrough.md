# Turmeric Smoke Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Turmeric smoke walkthrough — a repeatable, committed `canopy:walkthrough` run that exercises the ACE → Drive → ace-web flow against prod, with the new delete-opp feature enabling clean teardown.

**Architecture:** Two setup scripts (`turmeric_web_setup.py`, `turmeric_cli_setup.sh`) converge on "Turmeric opp exists in Drive." A single `turmeric.yaml` verification walkthrough renders the workbench and tears down via a new `DELETE /api/opps/<slug>/` endpoint. A shared `turmeric_pdd_finder.py` module reads the latest Turmeric PDD from the `Program Design Docs (PDDs)` subfolder of the ACE Drive root and seeds both paths.

**Tech Stack:** Django 5 + DRF (backend), React 19 + shadcn/ui (frontend), Google Drive API via existing `DriveClient` ABC, Playwright (web setup), `claude -p` + `ace-upload` (CLI setup), `canopy:walkthrough` skill (verification).

**Spec reference:** `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md`.

**R1 resolution:** The CLI path uses the API to create the opp (same as the web path via a Python helper, not the wizard UI) with the PDD body seeded as the `idea` field, then invokes `claude -p "/ace:run <slug> --dry-run --mode auto"` against the existing folder. The orchestrator runs `idea-to-pdd` against the seeded idea just as it would for any real opp. The resulting `.jsonl` transcript is uploaded via `ace-upload`. This preserves "full `/ace:run` behaviour tested" without the orchestrator needing a pre-existing `pdd.md`.

---

## File structure

### New files

```
apps/opps/tests/test_delete.py             # Delete endpoint tests
frontend/src/components/opps/DeleteOppDialog.tsx
docs/walkthroughs/turmeric.yaml
docs/walkthroughs/README.md
tools/walkthrough/__init__.py
tools/walkthrough/turmeric_pdd_finder.py
tools/walkthrough/turmeric_web_setup.py
tools/walkthrough/turmeric_cli_setup.sh
tools/walkthrough/tests/__init__.py
tools/walkthrough/tests/test_turmeric_pdd_finder.py
```

### Modified files

```
apps/opps/drive_client.py                  # Add trash_folder() to ABC + GoogleDriveClient
apps/opps/tests/fixtures/fake_drive.py     # Add trash_folder() to FakeDriveClient
apps/opps/sync.py                          # Add delete_opp_folder() helper
apps/opps/views.py                         # Add delete_opp view
apps/opps/urls.py                          # Wire DELETE route
frontend/src/api/opps.ts                   # Add deleteOpp()
frontend/src/pages/OppListPage.tsx         # Trash icon on each row
frontend/src/components/opps/WorkbenchHeader.tsx  # Add delete menu item
```

---

## Task 1: `trash_folder` on the DriveClient ABC + GoogleDriveClient

**Files:**
- Modify: `apps/opps/drive_client.py`
- Test: `apps/opps/tests/test_drive_client_writes.py` (additions)

- [ ] **Step 1: Write the failing test**

Add to `apps/opps/tests/test_drive_client_writes.py`:

```python
def test_trash_folder_marks_item_trashed(mock_drive_service):
    client = GoogleDriveClient.__new__(GoogleDriveClient)
    client._service = mock_drive_service
    mock_drive_service.files().update.return_value.execute.return_value = {"id": "abc123"}

    client.trash_folder("abc123")

    mock_drive_service.files().update.assert_called_with(
        fileId="abc123",
        body={"trashed": True},
        supportsAllDrives=True,
    )
```

If there's no `mock_drive_service` fixture in the existing file, reuse whatever mock pattern the sibling tests (e.g. `test_drive_client_writes.py::test_upload_file`) use. Match it exactly.

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_drive_client_writes.py::test_trash_folder_marks_item_trashed -v
```

Expected: FAIL with `AttributeError: 'GoogleDriveClient' object has no attribute 'trash_folder'`.

- [ ] **Step 3: Add abstract method to `DriveClient`**

In `apps/opps/drive_client.py`, immediately after `copy_file`'s `@abstractmethod` block:

```python
    @abstractmethod
    def trash_folder(self, folder_id: str) -> None:
        """Move a folder (and all descendants) to Drive trash.

        Drive's native trash is 30-day recoverable. We do NOT permanently
        delete — that would defeat accidental-deletion recovery."""
```

- [ ] **Step 4: Implement `GoogleDriveClient.trash_folder`**

Add after `copy_file`:

```python
    def trash_folder(self, folder_id: str) -> None:
        self._service.files().update(
            fileId=folder_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest apps/opps/tests/test_drive_client_writes.py::test_trash_folder_marks_item_trashed -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/drive_client.py apps/opps/tests/test_drive_client_writes.py
git commit -m "feat(opps): add trash_folder to DriveClient"
```

---

## Task 2: `FakeDriveClient.trash_folder`

**Files:**
- Modify: `apps/opps/tests/fixtures/fake_drive.py`

- [ ] **Step 1: Write the failing test**

Add to `apps/opps/tests/fixtures/fake_drive.py` the following test in a new `__main__`-style docstring, OR create a smoke test in `apps/opps/tests/test_drive_client.py`:

```python
def test_fake_drive_trash_folder_removes_from_listings():
    tree = {
        "ACE": {
            "doomed": {"opp.yaml": "slug: doomed"},
            "alive": {"opp.yaml": "slug: alive"},
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    doomed_id = fake.folder_id("ACE/doomed")
    fake.trash_folder(doomed_id)
    names = {f.name for f in fake.list_files(fake.folder_id("ACE"))}
    assert names == {"alive"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest apps/opps/tests/test_drive_client.py::test_fake_drive_trash_folder_removes_from_listings -v
```

Expected: FAIL (`AttributeError: 'FakeDriveClient' object has no attribute 'trash_folder'`).

- [ ] **Step 3: Implement on FakeDriveClient**

In `apps/opps/tests/fixtures/fake_drive.py`, add this method to `FakeDriveClient`:

```python
    def trash_folder(self, folder_id: str) -> None:
        node = self._nodes_by_id.get(folder_id)
        if node is None or node.parent_id is None:
            return
        parent = self._nodes_by_id[node.parent_id]
        parent.children.pop(node.name, None)
        # Recursively drop descendants from the id index so get_file 404s.
        def _drop(n):
            for child in list(n.children.values()):
                _drop(child)
            self._nodes_by_id.pop(n.id, None)
        _drop(node)
```

- [ ] **Step 4: Run test**

```bash
pytest apps/opps/tests/test_drive_client.py::test_fake_drive_trash_folder_removes_from_listings -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/tests/fixtures/fake_drive.py apps/opps/tests/test_drive_client.py
git commit -m "test(opps): add trash_folder to FakeDriveClient"
```

---

## Task 3: `delete_opp_folder` helper in `sync.py`

**Files:**
- Modify: `apps/opps/sync.py`
- Test: `apps/opps/tests/test_sync_structured.py` (additions)

- [ ] **Step 1: Write the failing test**

Add to `apps/opps/tests/test_sync_structured.py`:

```python
def test_delete_opp_folder_trashes_slug_folder(db):
    tree = {
        "ACE": {
            "doomed": {"opp.yaml": "slug: doomed\ndisplay_name: Doomed\n"},
            "alive": {"opp.yaml": "slug: alive\ndisplay_name: Alive\n"},
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    ace_id = fake.folder_id("ACE")

    from apps.opps.sync import delete_opp_folder
    delete_opp_folder(fake, ace_folder_id=ace_id, slug="doomed")

    remaining = {f.name for f in fake.list_files(ace_id)}
    assert remaining == {"alive"}


def test_delete_opp_folder_raises_on_missing(db):
    tree = {"ACE": {"alive": {"opp.yaml": "slug: alive\n"}}}
    fake = FakeDriveClient.from_tree(tree)
    ace_id = fake.folder_id("ACE")

    from apps.opps.sync import delete_opp_folder
    import pytest
    with pytest.raises(FileNotFoundError):
        delete_opp_folder(fake, ace_folder_id=ace_id, slug="ghost")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest apps/opps/tests/test_sync_structured.py::test_delete_opp_folder_trashes_slug_folder apps/opps/tests/test_sync_structured.py::test_delete_opp_folder_raises_on_missing -v
```

Expected: FAIL (`ImportError: cannot import name 'delete_opp_folder'`).

- [ ] **Step 3: Implement `delete_opp_folder`**

Append to `apps/opps/sync.py`:

```python
def delete_opp_folder(client: DriveClient, *, ace_folder_id: str, slug: str) -> None:
    """Trash the `ACE/<slug>/` folder. Raises FileNotFoundError if missing."""
    for child in client.list_files(ace_folder_id):
        if child.name == slug and child.mime_type == "application/vnd.google-apps.folder":
            client.trash_folder(child.id)
            return
    raise FileNotFoundError(f"no opp folder named {slug!r} under ACE root")
```

- [ ] **Step 4: Run tests**

```bash
pytest apps/opps/tests/test_sync_structured.py::test_delete_opp_folder_trashes_slug_folder apps/opps/tests/test_sync_structured.py::test_delete_opp_folder_raises_on_missing -v
```

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/sync.py apps/opps/tests/test_sync_structured.py
git commit -m "feat(opps): delete_opp_folder helper"
```

---

## Task 4: `DELETE /api/opps/<slug>/` endpoint

**Files:**
- Modify: `apps/opps/views.py`, `apps/opps/urls.py`
- Test: `apps/opps/tests/test_delete.py` (new)

- [ ] **Step 1: Write failing tests**

Create `apps/opps/tests/test_delete.py`:

```python
"""Tests for DELETE /api/opps/<slug>/."""
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import (
    FakeDriveClient,
    malaria_pilot_structured_tree,
)
from apps.sessions.models import Session


@pytest.fixture
def authed_user(db):
    return User.objects.create(email="deleter@dimagi.com", display_name="Deleter")


@pytest.fixture
def authed_client(authed_user):
    c = Client()
    c.force_login(authed_user)
    return c


def test_delete_opp_success_returns_204(authed_client, authed_user):
    fake = FakeDriveClient.from_tree(malaria_pilot_structured_tree())
    ace_id = fake.folder_id("ACE")
    # Seed a linked Session so we can assert cascade delete.
    Session.objects.create(
        owner=authed_user, title="linked", backend_kind="cli",
        status="active", source="web", opp_slug="malaria-pilot",
    )
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        response = authed_client.delete("/api/opps/malaria-pilot/")

    assert response.status_code == 204
    # Folder is gone from Drive.
    assert "malaria-pilot" not in {f.name for f in fake.list_files(ace_id)}
    # Linked session is deleted.
    assert Session.objects.filter(opp_slug="malaria-pilot").count() == 0


def test_delete_opp_missing_returns_404(authed_client):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        response = authed_client.delete("/api/opps/ghost/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "opp-not-found"


def test_delete_opp_unauthenticated_returns_401():
    c = Client()
    response = c.delete("/api/opps/malaria-pilot/")
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest apps/opps/tests/test_delete.py -v
```

Expected: all three FAIL (the DELETE route doesn't exist — returns 405 or similar).

- [ ] **Step 3: Add the view**

In `apps/opps/views.py`, add:

```python
from apps.opps.sync import delete_opp_folder, load_opp


@api_view(["DELETE"])
@permission_classes([AllowAny])  # auth enforced inline via _require_drive
def delete_opp(request, slug: str):
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        delete_opp_folder(client, ace_folder_id=ace_folder_id, slug=slug)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    with transaction.atomic():
        Session.objects.filter(opp_slug=slug).delete()

    return Response(status=204)
```

- [ ] **Step 4: Wire the route**

In `apps/opps/urls.py`, add to `urlpatterns`:

```python
    path("<slug:slug>/", views.delete_opp, name="opps-delete"),
```

Place it **before** the existing `<slug:slug>` route that resolves to `workbench` — Django matches the first matching pattern, and the trailing slash distinguishes the DELETE path.

Wait — look at existing routes. Both `workbench` (`<slug:slug>`) and the new `delete_opp` (`<slug:slug>/`) differ only by trailing slash. Django will treat them as distinct patterns. To avoid relying on the trailing slash, simply use the same path and let DRF dispatch on HTTP verb:

Replace the existing `path("<slug:slug>", views.workbench, name="opps-workbench"),` line with:

```python
    path("<slug:slug>", views.opp_resource, name="opps-resource"),
```

Then in `views.py`, add a thin dispatcher:

```python
@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])
def opp_resource(request, slug: str):
    if request.method == "DELETE":
        return delete_opp(request, slug)
    return workbench(request, slug)
```

And remove the `@api_view` decorator from `delete_opp` (it's now called via `opp_resource`). Same for `workbench` — remove its `@api_view` so the decorator doesn't double-wrap.

Actually a cleaner approach: keep the existing `workbench` decorator, and make the new route separate. Django Router ordering matters: the MORE SPECIFIC route must come first. The current `<slug:slug>` route is too greedy. The clean fix:

1. Leave `workbench` as-is (still `@api_view(["GET"])`).
2. Change its decorator to `@api_view(["GET", "DELETE"])`.
3. Inside `workbench`, branch on method:

```python
@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])
def workbench(request, slug: str):
    if request.method == "DELETE":
        return delete_opp(request, slug)
    # ... existing GET body unchanged ...
```

And `delete_opp` becomes a plain function (no `@api_view`) because `workbench` already carries the decorator.

Use this approach. Update Task 3 step 3 accordingly — `delete_opp` is a plain function, not `@api_view`-decorated.

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest apps/opps/tests/test_delete.py -v
```

Expected: all three PASS.

- [ ] **Step 6: Confirm other opps tests still pass**

```bash
pytest apps/opps/ -v
```

Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_delete.py
git commit -m "feat(opps): DELETE /api/opps/<slug>/ endpoint"
```

---

## Task 5: Frontend API client `deleteOpp()`

**Files:**
- Modify: `frontend/src/api/opps.ts`

- [ ] **Step 1: Add the API method**

In `frontend/src/api/opps.ts`, after `createOpp`:

```typescript
export function deleteOpp(slug: string): Promise<void> {
  return request<void>(`/opps/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
}
```

- [ ] **Step 2: Confirm `request()` handles 204 responses**

Open `frontend/src/api/client.ts` and verify `request()` doesn't choke on an empty body for 204. If it tries to `response.json()` unconditionally, adjust to return `undefined` when `response.status === 204`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/opps.ts frontend/src/api/client.ts
git commit -m "feat(opps): deleteOpp API client"
```

---

## Task 6: `DeleteOppDialog` component

**Files:**
- Create: `frontend/src/components/opps/DeleteOppDialog.tsx`

- [ ] **Step 1: Create the component**

```typescript
import { useState } from "react";
import { toast } from "sonner";

import { deleteOpp } from "@/api/opps";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  displayName: string;
  onDeleted?: () => void;
}

export function DeleteOppDialog({
  open,
  onOpenChange,
  slug,
  displayName,
  onDeleted,
}: Props) {
  const [submitting, setSubmitting] = useState(false);

  async function handleDelete() {
    setSubmitting(true);
    try {
      await deleteOpp(slug);
      toast.success(`Deleted ${displayName}`);
      onOpenChange(false);
      onDeleted?.();
    } catch (e) {
      toast.error(`Delete failed: ${String((e as Error).message ?? e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete {displayName}?</DialogTitle>
          <DialogDescription>
            This moves <code className="font-mono">ACE/{slug}</code> to
            Google Drive's trash (recoverable for 30 days) and deletes any
            chat sessions linked to this opp. Cannot be undone from ace-web.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={handleDelete}
            disabled={submitting}
          >
            {submitting ? "Deleting..." : "Delete opp"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Verify the component builds**

```bash
cd frontend && bun run build
```

Expected: clean build, no TS errors.

- [ ] **Step 3: Commit**

```bash
cd ..
git add frontend/src/components/opps/DeleteOppDialog.tsx
git commit -m "feat(opps): DeleteOppDialog component"
```

---

## Task 7: Trash button on the opp list rows

**Files:**
- Modify: `frontend/src/pages/OppListPage.tsx`

- [ ] **Step 1: Read the file to locate the row rendering**

Read `frontend/src/pages/OppListPage.tsx` end-to-end to find where each `OppCard` is rendered.

- [ ] **Step 2: Wire state for the delete dialog**

At the top of the component (after existing useState calls):

```typescript
const [deleteTarget, setDeleteTarget] = useState<OppCard | null>(null);
```

Import `Trash2` from `lucide-react` and `DeleteOppDialog` from `@/components/opps/DeleteOppDialog`.

- [ ] **Step 3: Add the trash icon to each row**

Inside the row JSX (next to the existing row content), add:

```tsx
<button
  type="button"
  aria-label={`Delete ${opp.slug}`}
  onClick={(e) => {
    e.preventDefault();
    e.stopPropagation();
    setDeleteTarget(opp);
  }}
  className="opacity-0 group-hover:opacity-100 transition-opacity p-2 hover:bg-destructive/10 hover:text-destructive rounded"
>
  <Trash2 className="h-4 w-4" />
</button>
```

The row's parent must have `className="group ..."` for the hover-reveal. If it doesn't already, add `group` to its classList.

- [ ] **Step 4: Render the dialog**

Near the bottom of the component's return (alongside `<NewOppDialog>`):

```tsx
{deleteTarget && (
  <DeleteOppDialog
    open={true}
    onOpenChange={(v) => { if (!v) setDeleteTarget(null); }}
    slug={deleteTarget.slug}
    displayName={deleteTarget.display_name}
    onDeleted={() => {
      setDeleteTarget(null);
      load();
    }}
  />
)}
```

- [ ] **Step 5: Manual verification against the local dev stack**

```bash
docker compose up -d
```

Wait for health. Then navigate to `http://localhost:8000/ace/opps`, hover a row, click trash, confirm. Verify the row disappears from the list after the toast.

If you cannot run the full stack (prod-only), note this in the commit message and defer to Task 14's full-prod run.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/OppListPage.tsx
git commit -m "feat(opps): trash button on opp list rows"
```

---

## Task 8: Delete menu item in workbench header

**Files:**
- Modify: `frontend/src/components/opps/WorkbenchHeader.tsx`

- [ ] **Step 1: Read the header to find the existing action affordances**

Read `frontend/src/components/opps/WorkbenchHeader.tsx` end-to-end. It likely has a `<Button>` or dropdown menu for "Compare runs" / "Fork" — the delete action sits alongside as a destructive sibling.

- [ ] **Step 2: Add the delete state + dialog**

Import `Trash2` and `DeleteOppDialog`, add `useNavigate` from `react-router-dom`. Inside the component:

```typescript
const navigate = useNavigate();
const [deleteOpen, setDeleteOpen] = useState(false);
```

Add a destructive-styled button next to the existing actions:

```tsx
<Button
  variant="ghost"
  size="sm"
  className="text-destructive hover:text-destructive hover:bg-destructive/10"
  onClick={() => setDeleteOpen(true)}
  aria-label="Delete opp"
>
  <Trash2 className="h-4 w-4" />
</Button>

<DeleteOppDialog
  open={deleteOpen}
  onOpenChange={setDeleteOpen}
  slug={opp.slug}
  displayName={opp.display_name}
  onDeleted={() => navigate("/opps")}
/>
```

`opp.slug` and `opp.display_name` are already props on `WorkbenchHeader` — confirm from the component signature; if they're nested under a `snapshot` prop, drill in accordingly.

- [ ] **Step 3: Build to verify no TS errors**

```bash
cd frontend && bun run build
```

Expected: clean build.

- [ ] **Step 4: Commit**

```bash
cd ..
git add frontend/src/components/opps/WorkbenchHeader.tsx
git commit -m "feat(opps): delete action in workbench header"
```

---

## Task 9: `turmeric_pdd_finder` module + tests

**Files:**
- Create: `tools/walkthrough/__init__.py`
- Create: `tools/walkthrough/turmeric_pdd_finder.py`
- Create: `tools/walkthrough/tests/__init__.py`
- Create: `tools/walkthrough/tests/test_turmeric_pdd_finder.py`

- [ ] **Step 1: Create package scaffolding**

```bash
mkdir -p tools/walkthrough/tests
touch tools/walkthrough/__init__.py tools/walkthrough/tests/__init__.py
```

- [ ] **Step 2: Write failing tests**

Create `tools/walkthrough/tests/test_turmeric_pdd_finder.py`:

```python
"""Tests for find_latest_turmeric_pdd against a FakeDriveClient."""
import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from tools.walkthrough.turmeric_pdd_finder import (
    PDDFinderError,
    find_latest_turmeric_pdd,
)


def _tree_with_two_pdd_folders() -> dict:
    return {
        "ACE": {
            "Program Design Docs (PDDs)": {
                "turmeric-v1.md": "old turmeric body",
                "turmeric-v2-updated.md": "new turmeric body",
                "malaria-v1.md": "unrelated",
            },
            "other-folder": {"nope.md": "nothing"},
        }
    }


def test_finds_most_recently_modified_turmeric_pdd():
    fake = FakeDriveClient.from_tree(_tree_with_two_pdd_folders())
    # Override modified_time so v2 is newer.
    fake.set_modified_time("ACE/Program Design Docs (PDDs)/turmeric-v1.md", "2026-01-01T00:00:00Z")
    fake.set_modified_time("ACE/Program Design Docs (PDDs)/turmeric-v2-updated.md", "2026-04-10T00:00:00Z")

    title, body = find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
    assert title == "turmeric-v2-updated.md"
    assert body == "new turmeric body"


def test_matches_pdd_folder_case_insensitively():
    tree = {
        "ACE": {
            "program design docs": {"turmeric.md": "body"},
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    title, body = find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
    assert title == "turmeric.md"


def test_raises_when_no_pdd_folder():
    fake = FakeDriveClient.from_tree({"ACE": {"other": {"turmeric.md": "x"}}})
    with pytest.raises(PDDFinderError, match="no PDD folder"):
        find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))


def test_raises_when_no_turmeric_file():
    fake = FakeDriveClient.from_tree({
        "ACE": {"Program Design Docs (PDDs)": {"malaria.md": "x"}}
    })
    with pytest.raises(PDDFinderError, match="no turmeric"):
        find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
```

- [ ] **Step 3: Add `FakeDriveClient.set_modified_time` helper**

The tests assume this helper exists; add it to `apps/opps/tests/fixtures/fake_drive.py`:

```python
    def set_modified_time(self, path: str, iso_timestamp: str) -> None:
        """Set modified_time on a file-by-path, for test ordering setups."""
        node = self._nodes_by_id[self.folder_id(path)]
        node.modified_time = iso_timestamp
```

Add `modified_time: str | None = None` to the `_Node` dataclass. Update `_to_drive_file`-equivalent path construction (search `DriveFile(` calls in `fake_drive.py`) to pass `modified_time=node.modified_time`.

- [ ] **Step 4: Run tests — verify they fail**

```bash
pytest tools/walkthrough/tests/test_turmeric_pdd_finder.py -v
```

Expected: FAIL (`ModuleNotFoundError` on the finder import).

- [ ] **Step 5: Implement the finder**

Create `tools/walkthrough/turmeric_pdd_finder.py`:

```python
"""Find the most recently modified Turmeric PDD under the ACE Drive root.

Used by both the web and CLI Turmeric smoke-test setup scripts. Reads through
the shared DriveClient abstraction so tests run against FakeDriveClient.
"""
from __future__ import annotations

from apps.opps.drive_client import DriveClient


class PDDFinderError(RuntimeError):
    """Raised when the PDD folder or the Turmeric file cannot be located."""


def _is_folder(mime: str) -> bool:
    return mime == "application/vnd.google-apps.folder"


def find_latest_turmeric_pdd(
    client: DriveClient, *, ace_folder_id: str
) -> tuple[str, str]:
    """Return (title, body) of the most recent Turmeric PDD.

    Two-step lookup:
      1. Under ace_folder_id, find a subfolder whose name contains
         'PDD' or 'Program Design Doc' (case-insensitive). If multiple
         match, pick the most recently modified.
      2. Inside that folder, find files whose name contains 'turmeric'
         (case-insensitive). Pick the most recent by modified_time.

    Raises PDDFinderError if either step finds nothing.
    """
    pdd_folders = [
        f for f in client.list_files(ace_folder_id)
        if _is_folder(f.mime_type)
        and (
            "pdd" in f.name.lower()
            or "program design doc" in f.name.lower()
        )
    ]
    if not pdd_folders:
        raise PDDFinderError(
            f"no PDD folder found under ACE root {ace_folder_id!r} "
            "(looked for names containing 'PDD' or 'Program Design Doc')"
        )
    pdd_folders.sort(key=lambda f: f.modified_time or "", reverse=True)
    pdd_folder = pdd_folders[0]

    turmeric_files = [
        f for f in client.list_files(pdd_folder.id)
        if not _is_folder(f.mime_type) and "turmeric" in f.name.lower()
    ]
    if not turmeric_files:
        raise PDDFinderError(
            f"no turmeric file in PDD folder {pdd_folder.name!r}"
        )
    turmeric_files.sort(key=lambda f: f.modified_time or "", reverse=True)
    picked = turmeric_files[0]

    content = client.get_content(picked.id, picked.mime_type)
    return picked.name, content.content


if __name__ == "__main__":
    # Convenience: `python -m tools.walkthrough.turmeric_pdd_finder --print-body`
    # prints only the body to stdout. Used by turmeric_cli_setup.sh.
    import argparse
    import sys
    from django.conf import settings
    from apps.opps.drive_client import get_drive_client
    import django

    django.setup()

    parser = argparse.ArgumentParser()
    parser.add_argument("--print-body", action="store_true")
    parser.add_argument("--print-title", action="store_true")
    args = parser.parse_args()

    ace_root = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    if not ace_root:
        print("ACE_DRIVE_ROOT_FOLDER_ID not configured", file=sys.stderr)
        sys.exit(2)

    client = get_drive_client()
    try:
        title, body = find_latest_turmeric_pdd(client, ace_folder_id=ace_root)
    except PDDFinderError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(3)

    if args.print_title:
        print(title)
    elif args.print_body:
        print(body)
    else:
        print(f"{title}\n---\n{body}")
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
pytest tools/walkthrough/tests/test_turmeric_pdd_finder.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/walkthrough/__init__.py tools/walkthrough/turmeric_pdd_finder.py \
  tools/walkthrough/tests/ apps/opps/tests/fixtures/fake_drive.py
git commit -m "feat(walkthrough): turmeric_pdd_finder module"
```

---

## Task 10: Web setup script (`turmeric_web_setup.py`)

**Files:**
- Create: `tools/walkthrough/turmeric_web_setup.py`

- [ ] **Step 1: Confirm dependencies**

The repo already has `playwright` installed for the e2e suite. Confirm with:

```bash
grep playwright e2e/package.json pyproject.toml
```

If a Python Playwright dependency is needed (this script is Python, not Node), add `playwright = "*"` to the `[project.optional-dependencies.e2e]` group in `pyproject.toml` and run:

```bash
uv sync --extra e2e
```

Expected: `playwright` installed in the Python venv.

- [ ] **Step 2: Create the script**

```python
"""Create a Turmeric smoke-test opp via the ace-web wizard on prod.

Uses a Playwright persistent profile at ~/.ace/playwright-profile/ so OAuth
cookies are reused across runs. First run requires an interactive login.

Exit codes:
  0 — opp created and visible in /opps/<slug>/
  2 — config error (missing env, missing profile dir)
  3 — PDD Finder failed (no Turmeric PDD, no PDD folder)
  4 — wizard flow failed (selector not found, form error)
  5 — opp-not-visible-after-create timeout
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

# Django bootstrap so we can use the Drive client via the PDD finder.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402

from apps.opps.drive_client import get_drive_client  # noqa: E402
from tools.walkthrough.turmeric_pdd_finder import (  # noqa: E402
    PDDFinderError,
    find_latest_turmeric_pdd,
)

BASE_URL = "https://labs.connect.dimagi.com/ace"
PROFILE_DIR = Path.home() / ".ace" / "playwright-profile"
SLUG_FILE = Path("/tmp/turmeric-smoketest-slug.txt")


def _log(msg: str) -> None:
    print(f"[web-setup] {msg}", file=sys.stderr)


def _compute_slug() -> str:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    return f"turmeric-smoketest-{stamp}"


def _ensure_profile_dir() -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-cleanup", action="store_true",
                        help="Delete leftover turmeric-smoketest-* opps before creating a new one.")
    args = parser.parse_args()

    ace_root = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    if not ace_root:
        _log("ACE_DRIVE_ROOT_FOLDER_ID not configured"); return 2

    _log("looking up latest Turmeric PDD in Drive...")
    try:
        title, body = find_latest_turmeric_pdd(
            get_drive_client(), ace_folder_id=ace_root
        )
    except PDDFinderError as exc:
        _log(f"PDD finder failed: {exc}"); return 3
    _log(f"using PDD: {title} ({len(body)} chars)")

    _ensure_profile_dir()
    slug = _compute_slug()
    display_name = f"Turmeric Smoketest {slug.split('-', 2)[-1]}"

    from playwright.sync_api import sync_playwright  # local import

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False,
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()

            if args.force_cleanup:
                _cleanup_leftovers(page)

            _log(f"navigating to {BASE_URL}/opps")
            page.goto(f"{BASE_URL}/opps", wait_until="networkidle")
            if "oauth" in page.url.lower() or "login" in page.url.lower():
                _log("OAuth required — complete login in the open browser, then re-run.")
                return 2

            _log(f"opening New Opp wizard, slug={slug}")
            page.get_by_role("button", name="New Opp").click()
            page.get_by_placeholder("malaria-pilot-2026").fill(slug)
            page.get_by_placeholder("Malaria Pilot 2026").fill(display_name)
            page.get_by_placeholder("Describe the intervention").fill(body)
            page.get_by_role("button", name="Create opp").click()

            page.wait_for_url(f"**/opps/{slug}**", timeout=30_000)
            _log(f"landed on /opps/{slug}")

            # Poll the API to confirm Drive sync completed.
            api_resp = page.request.get(f"{BASE_URL}/api/opps/{slug}")
            if api_resp.status != 200:
                _log(f"GET /api/opps/{slug} returned {api_resp.status}")
                return 5

            SLUG_FILE.write_text(slug)
            _log(f"wrote slug to {SLUG_FILE}")
            return 0
        except Exception as exc:  # noqa: BLE001 — narrow catch across Playwright surface
            _log(f"wizard flow failed: {exc!r}")
            return 4
        finally:
            context.close()


def _cleanup_leftovers(page) -> None:
    _log("force-cleanup: hitting DELETE /api/opps/* for existing turmeric-smoketest-* opps")
    resp = page.request.get(f"{BASE_URL}/api/opps/")
    if resp.status != 200:
        _log(f"can't list opps for cleanup (status {resp.status}); skipping")
        return
    data = resp.json().get("data", [])
    for card in data:
        if card.get("slug", "").startswith("turmeric-smoketest-"):
            _log(f"deleting leftover {card['slug']}")
            page.request.delete(f"{BASE_URL}/api/opps/{card['slug']}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Dry-run sanity test**

Because this hits prod, DO NOT run it blindly. Instead:
1. Confirm the Python imports and parser work:
   ```bash
   python -c "from tools.walkthrough.turmeric_web_setup import main; print('ok')"
   ```
   Expected: `ok`.
2. Full prod run is deferred to Task 14.

- [ ] **Step 4: Commit**

```bash
git add tools/walkthrough/turmeric_web_setup.py pyproject.toml
git commit -m "feat(walkthrough): turmeric web setup script"
```

---

## Task 11: CLI setup script (`turmeric_cli_setup.sh`)

**Files:**
- Create: `tools/walkthrough/turmeric_cli_setup.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# Turmeric CLI smoke-test setup.
#
# Flow:
#   1. Find the latest Turmeric PDD in Drive.
#   2. POST /api/opps/ on prod to create the opp (seeded with PDD body).
#   3. Run `claude -p "/ace:run <slug> --dry-run --mode auto"`.
#   4. Capture the resulting JSONL transcript path.
#   5. ace-upload the transcript.
#   6. Poll /api/opps/<slug>/ until 200 (Drive sync complete).
#   7. Write the slug to /tmp/turmeric-smoketest-slug.txt.
#
# Exit codes match turmeric_web_setup.py.
set -euo pipefail

BASE_URL="${ACE_WEB_BASE_URL:-https://labs.connect.dimagi.com/ace}"
CONFIG_TOML="${ACE_CONFIG_TOML:-$HOME/.ace/config.toml}"
SLUG_FILE="/tmp/turmeric-smoketest-slug.txt"
STAMP="$(date +%Y%m%d-%H%M)"
SLUG="turmeric-smoketest-${STAMP}"
DISPLAY_NAME="Turmeric Smoketest ${STAMP}"

log() { echo "[cli-setup] $*" >&2; }

# 0. Prereq checks
[ -f "$CONFIG_TOML" ] || { log "missing $CONFIG_TOML — run: ace-upload --configure"; exit 2; }
command -v claude >/dev/null || { log "claude CLI not on PATH"; exit 2; }
command -v ace-upload >/dev/null || { log "ace-upload CLI not on PATH"; exit 2; }

# 1. Fetch the latest Turmeric PDD (body) from Drive via the Python helper.
log "looking up latest Turmeric PDD..."
PDD_BODY="$(python -m tools.walkthrough.turmeric_pdd_finder --print-body)" || {
  log "PDD finder failed"; exit 3;
}
log "PDD body length: ${#PDD_BODY} chars"

# 2. Extract the personal token from ~/.ace/config.toml.
TOKEN="$(python -c "import tomllib; print(tomllib.load(open('$CONFIG_TOML', 'rb'))['token'])")"
SERVER="$(python -c "import tomllib; print(tomllib.load(open('$CONFIG_TOML', 'rb'))['server'])")"

# 3. POST /api/opps/ to create the opp.
log "creating opp $SLUG via API"
CREATE_PAYLOAD="$(python -c "
import json, sys
body = sys.stdin.read()
print(json.dumps({
  'slug': '$SLUG',
  'display_name': '$DISPLAY_NAME',
  'idea': body,
  'mode': 'auto',
}))
" <<< "$PDD_BODY")"

HTTP_CODE=$(curl -sS -o /tmp/opp-create-resp.json -w "%{http_code}" \
  -X POST "$SERVER/api/opps/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  --data-raw "$CREATE_PAYLOAD")
if [ "$HTTP_CODE" != "201" ]; then
  log "POST /api/opps/ returned $HTTP_CODE — body:"
  cat /tmp/opp-create-resp.json >&2
  exit 4
fi

# 4. Invoke /ace:run via `claude -p`.
log "running /ace:run $SLUG --dry-run --mode auto"
JSONL_PATH="/tmp/turmeric-cli-transcript-${STAMP}.jsonl"
claude -p "/ace:run $SLUG --dry-run --mode auto" \
  --output-format stream-json --verbose \
  > "$JSONL_PATH"
log "transcript: $JSONL_PATH ($(wc -l < "$JSONL_PATH") lines)"

# 5. Upload the transcript.
log "uploading transcript via ace-upload"
ace-upload "$JSONL_PATH" || { log "ace-upload failed"; exit 4; }

# 6. Poll the opp endpoint until it's browsable.
log "polling $SERVER/api/opps/$SLUG/ for Drive sync..."
for i in $(seq 1 30); do
  HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" "$SERVER/api/opps/$SLUG")
  if [ "$HTTP_CODE" = "200" ]; then log "opp visible"; break; fi
  sleep 2
done
[ "$HTTP_CODE" = "200" ] || { log "opp never became visible"; exit 5; }

# 7. Write slug.
echo "$SLUG" > "$SLUG_FILE"
log "wrote slug to $SLUG_FILE"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x tools/walkthrough/turmeric_cli_setup.sh
```

- [ ] **Step 3: Shellcheck**

```bash
shellcheck tools/walkthrough/turmeric_cli_setup.sh || true
```

Resolve any warnings shellcheck reports. If shellcheck is not installed, skip this step (noted in the walkthrough README's troubleshooting).

- [ ] **Step 4: Commit**

```bash
git add tools/walkthrough/turmeric_cli_setup.sh
git commit -m "feat(walkthrough): turmeric CLI setup script"
```

---

## Task 12: Walkthrough YAML

**Files:**
- Create: `docs/walkthroughs/turmeric.yaml`

- [ ] **Step 1: Write the spec**

```yaml
name: "Turmeric Smoke Walkthrough"
narrative: "Verify the ACE → Drive → ace-web flow against prod end-to-end"
base_url: "https://labs.connect.dimagi.com/ace"

# OAuth state is expected to be in the browse persistent profile.
# If the first scene lands on OAuth login, the runner needs to re-auth.
# No auth: block — we assume valid session cookies.

personas:
  runner:
    name: "Smoke-Test Runner"
    role: "Dimagi engineer validating a pre-release"
    color: "#2563eb"
    intro: "The runner has just executed turmeric_web_setup.py or turmeric_cli_setup.sh. The slug is in /tmp/turmeric-smoketest-slug.txt. Their job now is to verify the opp renders correctly in ace-web and then tear it down."

scenes:
  - persona: runner
    title: "Opp list shows Turmeric"
    show: "Opp list at /opps shows a turmeric-smoketest-<timestamp> row at the top with a recent timestamp"
    impressive_because: "The opp created by setup is visible to the current user right away — no stale cache."

  - persona: runner
    title: "Workbench loads"
    show: "Navigate to /opps/<slug> (read slug from /tmp/turmeric-smoketest-slug.txt). Three-pane workbench renders: skills sidebar on the left, artifact main pane in the middle, chat panel on the right."
    impressive_because: "Drive read-through works — the app is reading the Turmeric folder live from Drive."

  - persona: runner
    title: "Phase 1 — idea-to-pdd"
    show: "Click idea-to-pdd in the skills sidebar. The main pane shows the step preview with non-empty artifact body."
    impressive_because: "The seeded PDD flowed through: ace-web pulls it from Drive and previews it inline."
    ai_quality: "Preview body should contain the Turmeric PDD text that was seeded at setup — not a generic placeholder."

  - persona: runner
    title: "Phase 1 — pdd artifact"
    show: "Click the pdd artifact. Preview body contains the Turmeric PDD body verbatim."
    impressive_because: "Idempotent round-trip: what went in via the setup script comes out in the workbench."
    ai_quality: "Body must match the source PDD that turmeric_pdd_finder pulled from Drive."

  - persona: runner
    title: "Phase 2 — Learn app summary"
    show: "Click pdd-to-learn-app in the sidebar. Preview renders with a non-empty body OR a clear placeholder indicating the step hasn't run yet."
    impressive_because: "Graceful degradation — if the CLI path ran in --dry-run, some phases may be stubs and the UI shows that honestly."

  - persona: runner
    title: "Phase 4 — OCS agent config"
    show: "Click ocs-agent-setup in the sidebar. Preview renders the OCS agent config artifact."
    impressive_because: "Phases beyond 1 still render as artifacts when present."

  - persona: runner
    title: "Phase 6 — cycle grade"
    show: "Click cycle-grade in the sidebar. Preview renders the closeout cycle-grade."
    impressive_because: "End-of-lifecycle artifacts are visible."

  - persona: runner
    title: "Discuss in chat from pdd step"
    show: "Click 'Discuss in chat' on the pdd step. A new chat tab opens with a seeded system message referencing pdd and the current slug."
    impressive_because: "The opps → chat bridge works: step context is pulled from Drive and used to seed a fresh ace-web session."
    ai_quality: "Seed message contains the skill name 'pdd' and the opp slug."

  - persona: runner
    title: "Teardown — delete the opp"
    show: "Return to /opps. Hover the turmeric-smoketest row, click the trash icon, confirm the destructive dialog. The row disappears from the list; redirected (or stays) cleanly."
    impressive_because: "The walkthrough cleans up after itself — the next smoke run starts from zero."
```

- [ ] **Step 2: Sanity-check YAML parses**

```bash
python -c "import yaml; yaml.safe_load(open('docs/walkthroughs/turmeric.yaml'))" && echo OK
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add docs/walkthroughs/turmeric.yaml
git commit -m "feat(walkthrough): turmeric verify walkthrough spec"
```

---

## Task 13: README for the walkthrough

**Files:**
- Create: `docs/walkthroughs/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Turmeric Smoke Walkthroughs

Repeatable end-to-end smoke tests for the ACE → Drive → ace-web flow against
prod (`labs.connect.dimagi.com/ace`). Two entry paths, one verify deck.

Spec: `docs/specs/2026-04-17-turmeric-smoke-walkthrough-design.md`.
Plan: `docs/plans/2026-04-17-turmeric-smoke-walkthrough.md`.

## What's verified

- Opp creation path works (wizard for web; `/ace:run` + `ace-upload` for CLI).
- Opp visible in `/opps` after setup.
- Workbench renders three-pane layout.
- Artifacts round-trip through Drive (PDD in, PDD out).
- "Discuss in chat" seeds a new chat session.
- Delete-opp teardown leaves Drive + DB clean.

## Prerequisites

- Logged-in Dimagi Google identity in a browser (for Drive + ace-web OAuth).
- `~/.ace/config.toml` with the `ace-upload` personal token and server URL.
  Generate the token from ace-web's Settings page.
- `claude` CLI on PATH and authenticated (CLI path only).
- `uv sync --extra e2e` to install Python Playwright (web path only).
- Persistent Playwright profile at `~/.ace/playwright-profile/`. First run of
  `turmeric_web_setup.py` opens a visible browser — complete OAuth there;
  subsequent runs reuse the cookies.

## Web path

```bash
python tools/walkthrough/turmeric_web_setup.py
# then in Claude Code:
/walkthrough turmeric
```

`turmeric_web_setup.py` creates a `turmeric-smoketest-<YYYYMMDD-HHMM>` opp
via the ace-web wizard, writes the slug to `/tmp/turmeric-smoketest-slug.txt`,
and exits 0 on success.

Flags:
- `--force-cleanup` — delete any leftover `turmeric-smoketest-*` opps before
  creating a new one. Use this when prior runs aborted mid-deck.

## CLI path

```bash
bash tools/walkthrough/turmeric_cli_setup.sh
# then in Claude Code:
/walkthrough turmeric
```

The CLI setup script creates the opp via the API, runs
`claude -p "/ace:run <slug> --dry-run --mode auto"`, captures the JSONL
transcript, and uploads it with `ace-upload`.

**Cost note:** `/ace:run --dry-run` still burns LLM tokens for the
orchestrator's planning + per-step dispatch. Budget a few dollars per run.

## Running the walkthrough deck

Inside a Claude Code session in the repo root:

```
/walkthrough turmeric
```

The skill reads `docs/walkthroughs/turmeric.yaml`, navigates through the
nine scenes, scores each one, and writes the HTML deck to
`screenshots/walkthroughs/turmeric.html`. The final scene tears down the
opp via the new DELETE endpoint.

## Troubleshooting

- **First Playwright run asks for OAuth:** complete login in the visible
  browser window and let it close. The persistent profile now has cookies
  for subsequent runs.
- **`/ace:run` hangs:** the Claude CLI session may have lost auth. Run
  `claude login` (or the Claude Code auth flow) and retry.
- **`ace-upload: Config not found`:** run `ace-upload --configure` and paste
  a personal token from ace-web's Settings page.
- **Leftover `turmeric-smoketest-*` opps:** either rerun setup with
  `--force-cleanup` (web) or delete manually from the UI.
- **Walkthrough scene 9 fails (delete button not found):** confirm the
  delete-opp UI shipped in this plan's Tasks 7–8.

## When to run this

- Before releasing a new ace-web or ACE plugin version.
- After infra migrations (DB, Drive credentials, OAuth provider).
- When a user reports "the workbench looks empty" to disambiguate
  rendering from upstream (Drive, ACE) problems.

Not suited for CI — LLM non-determinism + cost + prod-only dependencies.
```

- [ ] **Step 2: Commit**

```bash
git add docs/walkthroughs/README.md
git commit -m "docs(walkthrough): README for Turmeric smoke walkthrough"
```

---

## Task 14: First full runs — capture decks, fix low-scoring scenes

This task is **human-in-the-loop**. Do not complete it autonomously.

**Files:** runtime artifacts only (`screenshots/walkthroughs/turmeric.html` and `.json`). Any code fixes go into follow-up commits.

- [ ] **Step 1: Run the web path end-to-end**

```bash
python tools/walkthrough/turmeric_web_setup.py
```

Expected: exit 0, slug printed, `/tmp/turmeric-smoketest-slug.txt` written.

- [ ] **Step 2: Execute the walkthrough (web)**

Inside Claude Code, run:

```
/walkthrough turmeric
```

Let the skill drive through all nine scenes. The final scene deletes the opp.

Capture the resulting `screenshots/walkthroughs/turmeric.html` — open it and review each scene's score.

- [ ] **Step 3: Run the CLI path end-to-end**

```bash
bash tools/walkthrough/turmeric_cli_setup.sh
```

Expected: exit 0, transcript uploaded, slug written.

- [ ] **Step 4: Execute the walkthrough (CLI)**

```
/walkthrough turmeric
```

Review the second deck.

- [ ] **Step 5: Identify low-scoring scenes**

For any scene ≤ 2/5 on Demo Readiness or ≤ 2/5 on any other dimension:
- If **[CODE]** issue — file a follow-up task, fix in a new commit, rerun the failing scene only.
- If **[DATA]** issue — adjust the setup script or the PDD source.
- If **[SPEC]** issue — update the walkthrough YAML narration or scene order.

- [ ] **Step 6: Commit any fixes from Step 5**

One commit per logical fix. Reference the scene number in the commit message, e.g.:

```bash
git commit -m "fix(opps): workbench header overflow menu alignment (scene 2)"
```

- [ ] **Step 7: Final two clean runs**

Rerun both paths end-to-end with no low-score blockers. Commit the final HTML deck outputs (optional, if the team wants them as baselines):

```bash
git add screenshots/walkthroughs/turmeric.html screenshots/walkthroughs/turmeric.json
git commit -m "docs(walkthrough): baseline turmeric deck"
```

- [ ] **Step 8: Open PR**

```bash
gh pr create --title "Turmeric smoke walkthrough + delete-opp feature" --body "$(cat <<'EOF'
## Summary
- New `canopy:walkthrough` smoke test at `docs/walkthroughs/turmeric.yaml` that verifies the ACE → Drive → ace-web flow end-to-end against prod
- Two entry paths (web wizard via Playwright, CLI via `/ace:run` + `ace-upload`) share a single verification deck
- New `DELETE /api/opps/<slug>/` endpoint + trash-icon UI for clean teardown

## Test plan
- [ ] Backend unit tests: `pytest apps/opps/tests/test_delete.py -v`
- [ ] Full opps suite: `pytest apps/opps/ -v`
- [ ] PDD finder tests: `pytest tools/walkthrough/tests/ -v`
- [ ] Frontend build: `cd frontend && bun run build`
- [ ] Web-path walkthrough: `python tools/walkthrough/turmeric_web_setup.py && /walkthrough turmeric`
- [ ] CLI-path walkthrough: `bash tools/walkthrough/turmeric_cli_setup.sh && /walkthrough turmeric`
- [ ] Teardown scene cleans up the opp from Drive + DB

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-review notes

1. **Spec coverage:** every §3–§6 requirement maps to a task:
   - §3.1 two setup scripts + one walkthrough → Tasks 10, 11, 12
   - §3.2 PDD Finder → Task 9
   - §3.3 web setup → Task 10
   - §3.4 CLI setup → Task 11
   - §3.5 walkthrough YAML → Task 12
   - §4 nine scenes → Task 12
   - §5 delete API + UI → Tasks 1, 2, 3, 4, 5, 6, 7, 8
   - §6 prod-run contract → Task 13 (README) + Task 10's `--force-cleanup` flag
   - §7 R1 resolved in plan header
   - §8 file list matches

2. **Placeholder scan:** no `TBD`, `implement later`, or "add appropriate error handling" — all steps contain the exact code or exact commands to run. The only forward reference is Task 14's iterative fix loop, which is inherently open-ended by the nature of the walkthrough rubric.

3. **Type consistency:** `trash_folder` has the same signature everywhere (ABC + Google impl + Fake). `delete_opp_folder` signature is consistent across sync.py and its tests. `find_latest_turmeric_pdd` returns `tuple[str, str]` everywhere. `DeleteOppDialog` props are consistent between Task 6 definition and Tasks 7, 8 usage.
