# Web-Native Opp Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ace-web into the primary interface for building CRISPR-Connect opportunities end-to-end — no CLI commands required.

**Architecture:** Attached-chat model — every opp has a working chat session; web actions translate to chat messages, Claude (with ACE plugin installed) executes via the existing CLIBackend, Drive state changes broadcast via WebSocket, workbench observes and refetches. No new execution infrastructure.

**Tech Stack:** Django 5 + Channels (backend); React 19 + TypeScript + Tailwind 4 + shadcn (frontend); Google Drive API (data); WebSockets over existing channels-redis.

**Spec:** `docs/specs/2026-04-15-web-native-opp-lifecycle-design.md`

---

## Task 0: Drive client write surface

`DriveClient` is read-only today. Slices 1, 6, 7 need writes. Add `create_folder`, `upload_file`, `update_file`, `copy_file` to the ABC and implement in both `GoogleDriveClient` and `FakeDriveClient`.

**Files:**
- Modify: `apps/opps/drive_client.py`
- Modify: `apps/opps/tests/fixtures/fake_drive.py`
- Create: `apps/opps/tests/test_drive_client_writes.py`

- [ ] **Step 1: Write failing tests for FakeDriveClient writes**

```python
# apps/opps/tests/test_drive_client_writes.py
import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


def test_create_folder_inside_existing_folder():
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    new_id = fake.create_folder(parent_id=ace_id, name="malaria-pilot")
    children = fake.list_files(ace_id)
    assert any(f.id == new_id and f.name == "malaria-pilot" for f in children)


def test_upload_file_text():
    fake = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    folder_id = fake.folder_id("ACE/malaria-pilot")
    file_id = fake.upload_file(
        parent_id=folder_id, name="idea.md",
        content="# Malaria pilot\n", mime_type="text/markdown",
    )
    content = fake.get_content(file_id, "text/markdown")
    assert content.content == "# Malaria pilot\n"


def test_update_file_replaces_content():
    fake = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"idea.md": "# Old\n"}}
    })
    file_id = fake.file_id("ACE/malaria-pilot/idea.md")
    fake.update_file(file_id, content="# New\n", mime_type="text/markdown")
    assert fake.get_content(file_id, "text/markdown").content == "# New\n"


def test_copy_file_to_new_parent():
    fake = FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "runs": {
                    "run-001": {"idd.md": "# IDD body"},
                    "run-002": {},
                }
            }
        }
    })
    src_id = fake.file_id("ACE/malaria-pilot/runs/run-001/idd.md")
    dst_folder = fake.folder_id("ACE/malaria-pilot/runs/run-002")
    new_id = fake.copy_file(src_id, dst_folder, new_name="idd.md")
    assert fake.get_content(new_id, "text/markdown").content == "# IDD body"
```

- [ ] **Step 2: Run tests — expect failures**

Run: `uv run pytest apps/opps/tests/test_drive_client_writes.py -v`
Expected: 4 FAILED (AttributeError: FakeDriveClient has no attribute create_folder/upload_file/update_file/copy_file)

- [ ] **Step 3: Add abstract methods to DriveClient**

Edit `apps/opps/drive_client.py` — add to the ABC:

```python
class DriveClient(ABC):
    # ... existing read methods ...

    @abstractmethod
    def create_folder(self, parent_id: str, name: str) -> str:
        """Create a folder under parent_id. Returns new folder ID."""

    @abstractmethod
    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        """Create a new file under parent_id with the given content.
        Returns new file ID."""

    @abstractmethod
    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        """Replace the content of an existing file."""

    @abstractmethod
    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        """Copy a file to a new parent. Returns new file ID."""
```

- [ ] **Step 4: Implement the four methods on GoogleDriveClient**

Append to `GoogleDriveClient` in `apps/opps/drive_client.py`:

```python
    def create_folder(self, parent_id: str, name: str) -> str:
        body = {
            "name": name,
            "mimeType": self.FOLDER_MIME,
            "parents": [parent_id],
        }
        resp = self._service.files().create(
            body=body, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        from googleapiclient.http import MediaInMemoryUpload
        body = {"name": name, "parents": [parent_id]}
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
        resp = self._service.files().create(
            body=body, media_body=media, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
        self._service.files().update(
            fileId=file_id, media_body=media, supportsAllDrives=True
        ).execute()

    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        body = {"parents": [new_parent_id]}
        if new_name:
            body["name"] = new_name
        resp = self._service.files().copy(
            fileId=file_id, body=body, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]
```

- [ ] **Step 5: Implement the same methods on FakeDriveClient**

Inspect `apps/opps/tests/fixtures/fake_drive.py` to understand the tree/dict representation. Add:

```python
    def create_folder(self, parent_id: str, name: str) -> str:
        parent = self._node_by_id(parent_id)
        new_id = self._next_id()
        parent["children"][name] = {"id": new_id, "type": "folder", "children": {}}
        self._id_index[new_id] = parent["children"][name]
        return new_id

    def upload_file(self, parent_id, name, content, mime_type):
        parent = self._node_by_id(parent_id)
        new_id = self._next_id()
        node = {
            "id": new_id, "type": "file",
            "content": content, "mime_type": mime_type,
        }
        parent["children"][name] = node
        self._id_index[new_id] = node
        return new_id

    def update_file(self, file_id, content, mime_type):
        node = self._node_by_id(file_id)
        node["content"] = content
        node["mime_type"] = mime_type

    def copy_file(self, file_id, new_parent_id, new_name=None):
        src = self._node_by_id(file_id)
        return self.upload_file(
            new_parent_id, new_name or src.get("name", "copy"),
            src["content"], src["mime_type"],
        )
```

(Adapt names/structure to match the real `fake_drive.py` layout.)

- [ ] **Step 6: Run tests — expect pass**

Run: `uv run pytest apps/opps/tests/test_drive_client_writes.py -v`
Expected: 4 PASSED

- [ ] **Step 7: Run full suite — no regressions**

Run: `uv run pytest -q`
Expected: All previously-passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add apps/opps/drive_client.py apps/opps/tests/fixtures/fake_drive.py apps/opps/tests/test_drive_client_writes.py
git commit -m "feat(opps): add write surface (create_folder, upload_file, update_file, copy_file) to DriveClient"
```

---

## Task 1: OppWorkspace model

Add the Postgres anchor. Stores slug, display name, working-session pointer, created-by.

**Files:**
- Modify: `apps/opps/models.py` (replace the empty docstring)
- Modify: `apps/opps/apps.py` (no changes needed; already has `label = "opps"`)
- Create: `apps/opps/migrations/0001_initial.py` (via makemigrations)
- Create: `apps/opps/tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# apps/opps/tests/test_models.py
import pytest
from django.db import IntegrityError

from apps.auth.models import User
from apps.opps.models import OppWorkspace


@pytest.fixture
def user(db):
    return User.objects.create(email="jon@dimagi.com", display_name="Jon")


def test_create_opp_workspace(user, db):
    w = OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria Pilot", created_by=user,
    )
    assert w.slug == "malaria-pilot"
    assert w.working_session is None
    assert w.created_at is not None


def test_slug_uniqueness(user, db):
    OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="A", created_by=user,
    )
    with pytest.raises(IntegrityError):
        OppWorkspace.objects.create(
            slug="malaria-pilot", display_name="B", created_by=user,
        )
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/opps/tests/test_models.py -v`
Expected: ImportError (OppWorkspace doesn't exist)

- [ ] **Step 3: Replace `apps/opps/models.py` with the model**

```python
"""ORM models for the opps Workbench.

Intentionally lightweight. Drive remains the source of truth for opp
*content* (idea.md, pdd.md, artifacts, state.yaml, run history). This
Postgres row is just the workspace wrapper — pins the display name, the
currently-attached working chat session, and created-by metadata.

See: docs/specs/2026-04-15-web-native-opp-lifecycle-design.md § 4.2.
"""
from django.conf import settings
from django.db import models


class OppWorkspace(models.Model):
    slug = models.CharField(max_length=64, primary_key=True)
    display_name = models.CharField(max_length=200)
    working_session = models.ForeignKey(
        "sessions.Session",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="opp_working_for",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_opps",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opp_workspaces"
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.slug}: {self.display_name}"
```

- [ ] **Step 4: Generate migration**

Run: `uv run python manage.py makemigrations opps`
Expected: `apps/opps/migrations/0001_initial.py` created.

- [ ] **Step 5: Run tests**

Run: `uv run pytest apps/opps/tests/test_models.py -v`
Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add apps/opps/models.py apps/opps/migrations/0001_initial.py apps/opps/tests/test_models.py
git commit -m "feat(opps): add OppWorkspace model for opp metadata + working-session pointer"
```

---

## Task 2: Create-opp API endpoint (slice 1 backend)

`POST /api/opps/` creates a new opp: Drive folder tree, workspace row, seeded working session. All or nothing (transactional).

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Modify: `apps/opps/serializers.py`
- Create: `apps/opps/opp_creator.py`
- Create: `apps/opps/tests/test_create_opp.py`

- [ ] **Step 1: Write failing test**

```python
# apps/opps/tests/test_create_opp.py
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.sessions.models import Session


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client()
    c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def test_create_opp_happy_path(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/",
            data={
                "slug": "malaria-pilot",
                "display_name": "Malaria Pilot 2026",
                "idea": "Use ACE to pilot bed-net distribution...",
                "mode": "review",
            },
            content_type="application/json",
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert body["data"]["slug"] == "malaria-pilot"
    assert body["data"]["working_session_slug"]

    # Workspace row created
    w = OppWorkspace.objects.get(slug="malaria-pilot")
    assert w.display_name == "Malaria Pilot 2026"
    assert w.working_session is not None

    # Working session seeded with messages
    session = w.working_session
    assert session.opp_slug == "malaria-pilot"
    messages = list(session.messages.order_by("turn_index"))
    assert len(messages) == 2  # system + user
    assert "malaria-pilot" in messages[0].plaintext
    assert "/ace:" in messages[1].plaintext.lower() or "idea-to-pdd" in messages[1].plaintext.lower()

    # Drive folder created
    children = fake.list_files(ace_id)
    assert any(f.name == "malaria-pilot" for f in children)


def test_create_opp_slug_collision(authed_client, db):
    fake = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.post(
            "/api/opps/",
            data={"slug": "malaria-pilot", "display_name": "X", "idea": "Y", "mode": "review"},
            content_type="application/json",
        )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug-taken"


def test_create_opp_invalid_slug(authed_client, db):
    resp = authed_client.post(
        "/api/opps/",
        data={"slug": "Malaria Pilot", "display_name": "X", "idea": "Y", "mode": "review"},
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid-slug"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/opps/tests/test_create_opp.py -v`
Expected: 3 FAILED (endpoint doesn't exist yet)

- [ ] **Step 3: Implement opp creator**

```python
# apps/opps/opp_creator.py
"""Idempotent-ish opp creator. All-or-nothing within a transaction; Drive
write failures roll back the Postgres rows."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from apps.opps.drive_client import DriveClient
from apps.opps.models import OppWorkspace
from apps.sessions.models import Message, Session

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


class CreateOppError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CreateOppResult:
    slug: str
    workspace: OppWorkspace
    working_session: Session


def create_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    slug: str,
    display_name: str,
    idea: str,
    mode: str = "review",
) -> CreateOppResult:
    """Create a new opp: Drive folder + workspace row + seeded chat session."""
    if not SLUG_RE.match(slug):
        raise CreateOppError("invalid-slug", f"invalid slug {slug!r}")
    if mode not in ("auto", "review"):
        raise CreateOppError("invalid-mode", f"invalid mode {mode!r}")
    if OppWorkspace.objects.filter(slug=slug).exists():
        raise CreateOppError("slug-taken", f"opp {slug!r} already exists")
    # Drive-side collision
    for child in drive.list_files(ace_root_folder_id):
        if child.name == slug:
            raise CreateOppError("slug-taken", f"Drive folder {slug!r} already exists")

    # Drive writes (outside the Postgres transaction; if DB step fails, we
    # leave a harmless empty folder rather than risk a half-written DB).
    opp_folder_id = drive.create_folder(ace_root_folder_id, slug)
    runs_folder_id = drive.create_folder(opp_folder_id, "runs")
    run1_folder_id = drive.create_folder(runs_folder_id, "run-001")
    drive.upload_file(opp_folder_id, "idea.md", idea, "text/markdown")
    state_yaml = (
        f"opp: {slug}\n"
        f"mode: {mode}\n"
        f"current_run: run-001\n"
        f"phase: design-review\n"
    )
    drive.upload_file(run1_folder_id, "state.yaml", state_yaml, "application/yaml")

    # Transactional: workspace + working session + seed messages
    with transaction.atomic():
        session = Session.objects.create(
            owner=owner,
            title=f"{display_name} — working session",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id="run-001",
        )
        Message.objects.create(
            session=session, turn_index=0, role="system",
            sender_user=owner,
            content={"type": "system", "source": "opps-create"},
            plaintext=f"Opp `{slug}` created in {mode} mode. Initial idea is in idea.md.",
            status="complete",
        )
        Message.objects.create(
            session=session, turn_index=1, role="user",
            sender_user=owner,
            content={"type": "text"},
            plaintext=f"Run /ace:step idea-to-pdd for {slug}.",
            status="complete",
        )
        workspace = OppWorkspace.objects.create(
            slug=slug, display_name=display_name,
            working_session=session, created_by=owner,
        )

    return CreateOppResult(slug=slug, workspace=workspace, working_session=session)
```

- [ ] **Step 4: Add view + route**

Append to `apps/opps/views.py`:

```python
import json
from apps.opps.opp_creator import CreateOppError, create_opp


@api_view(["POST"])
@permission_classes([AllowAny])  # Drive availability enforced via _require_drive
def opp_create(request):
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
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return Response(error_response("invalid JSON", code="bad-json"), status=400)

    try:
        result = create_opp(
            drive=client, ace_root_folder_id=ace_folder_id, owner=request.user,
            slug=payload.get("slug", ""),
            display_name=payload.get("display_name", ""),
            idea=payload.get("idea", ""),
            mode=payload.get("mode", "review"),
        )
    except CreateOppError as exc:
        status = 409 if exc.code == "slug-taken" else 400
        return Response(error_response(str(exc), code=exc.code), status=status)

    return Response(
        success_response({
            "slug": result.slug,
            "working_session_slug": result.working_session.slug,
        }),
        status=201,
    )
```

Add to `apps/opps/urls.py` — insert **before** the `path("")` empty-path route so POST `/api/opps/` dispatches here; the empty-path route keeps the GET list:

```python
    path("", views.opp_list, name="opps-list"),  # existing; only GET reaches opp_list
    path("", views.opp_create, name="opps-create"),  # NEW — POST /api/opps/
```

Wait — Django URL routing is method-agnostic on the URL pattern. Use a single view that dispatches on method, OR use `@api_view(["GET"])` / `@api_view(["POST"])` separately and DRF will 405 on method mismatch. The cleaner approach: convert the existing `opp_list` to accept both methods, or use a combined view.

Actually Django is fine with two separate patterns if they have different names and the same path — DRF's `@api_view` restricts by method. But to be safe, combine into one view:

```python
# In apps/opps/views.py — replace existing opp_list signature:
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def opp_collection(request):
    if request.method == "POST":
        return opp_create(request)
    return opp_list(request)
```

Then `apps/opps/urls.py`:

```python
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_collection, name="opps-collection"),
    # ... rest unchanged ...
]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest apps/opps/tests/test_create_opp.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/opp_creator.py apps/opps/tests/test_create_opp.py
git commit -m "feat(opps): add POST /api/opps/ to create a new opp (Drive + workspace + seeded session)"
```

---

## Task 3: New Opp wizard UI (slice 1 frontend)

"+ New Opp" button on the opp list → shadcn Dialog with form.

**Files:**
- Create: `frontend/src/components/opps/NewOppDialog.tsx`
- Modify: `frontend/src/pages/OppListPage.tsx`
- Modify: `frontend/src/api/opps.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Add API client and types**

Append to `frontend/src/api/types.ts`:

```typescript
export interface CreateOppPayload {
  slug: string;
  display_name: string;
  idea: string;
  mode: "auto" | "review";
}

export interface CreateOppResponse {
  slug: string;
  working_session_slug: string;
}
```

Append to `frontend/src/api/opps.ts`:

```typescript
import type { CreateOppPayload, CreateOppResponse } from "./types";

export function createOpp(payload: CreateOppPayload): Promise<CreateOppResponse> {
  return request<CreateOppResponse>("/opps/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 2: Create NewOppDialog component**

```tsx
// frontend/src/components/opps/NewOppDialog.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createOpp } from "@/api/opps";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$/;

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}

export function NewOppDialog({ open, onOpenChange }: Props) {
  const navigate = useNavigate();
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [idea, setIdea] = useState("");
  const [mode, setMode] = useState<"auto" | "review">("review");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const slugValid = SLUG_RE.test(slug);
  const canSubmit = slugValid && displayName.trim() && idea.trim() && !submitting;

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      const result = await createOpp({ slug, display_name: displayName, idea, mode });
      navigate(`/opps/${result.slug}`);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create a new opp</DialogTitle>
          <DialogDescription>
            Creates <code className="font-mono">ACE/&lt;slug&gt;/</code> in Drive
            and starts a working chat session.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          <label className="flex flex-col gap-1 text-sm">
            Slug (kebab-case, must be unique)
            <Input
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase())}
              placeholder="malaria-pilot-2026"
              className={cn(slug && !slugValid && "border-destructive")}
            />
            {slug && !slugValid && (
              <span className="text-xs text-destructive">
                Lowercase letters, digits, hyphens. Can't start or end with a hyphen.
              </span>
            )}
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Display name
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Malaria Pilot 2026"
            />
          </label>

          <label className="flex flex-col gap-1 text-sm">
            Initial idea
            <textarea
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={6}
              className="rounded border border-border bg-card p-2 font-mono text-xs"
              placeholder="Describe the intervention: what, who, how..."
            />
          </label>

          <label className="flex items-center gap-3 text-sm">
            Mode:
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "review"}
                onChange={() => setMode("review")}
              />
              review (recommended)
            </label>
            <label className="flex items-center gap-1">
              <input
                type="radio"
                checked={mode === "auto"}
                onChange={() => setMode("auto")}
              />
              auto
            </label>
          </label>

          {error && (
            <div className="rounded border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
              {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {submitting ? "Creating…" : "Create opp"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Wire the button into OppListPage**

In `frontend/src/pages/OppListPage.tsx`, add a header row with the button:

```tsx
import { useState } from "react";
// ... existing imports ...
import { NewOppDialog } from "@/components/opps/NewOppDialog";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

// Inside the page component, near the top of the JSX:
const [newDialogOpen, setNewDialogOpen] = useState(false);

// Then in render, above the opp list:
<div className="flex items-center justify-between px-4 py-3">
  <h1 className="text-base font-semibold">Opportunities</h1>
  <Button size="sm" onClick={() => setNewDialogOpen(true)}>
    <Plus className="mr-1.5 h-3.5 w-3.5" />
    New Opp
  </Button>
</div>
<NewOppDialog open={newDialogOpen} onOpenChange={setNewDialogOpen} />
```

(Preserve whatever layout/header the current OppListPage already has; just insert the button on the right side of the top bar.)

- [ ] **Step 4: TypeScript check + manual smoke**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

Then `docker compose up`, open `/opps`, click "New Opp", fill the form, submit. Verify redirect to `/opps/<slug>` and a seeded chat exists.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/opps/NewOppDialog.tsx frontend/src/pages/OppListPage.tsx frontend/src/api/opps.ts frontend/src/api/types.ts
git commit -m "feat(opps): New Opp wizard on /opps with slug validation"
```

---

## Task 4: Attached chat panel (slice 2)

Extract the chat UI from `ChatPage.tsx` into a reusable `ChatPanel` component, then embed it as the right column of `OppWorkbenchPage`.

**Files:**
- Create: `frontend/src/components/opps/ChatPanel.tsx`
- Modify: `frontend/src/pages/ChatPage.tsx` (refactor to use ChatPanel)
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx` (embed the panel)
- Modify: `frontend/src/api/opps.ts` (new endpoint for getting/ensuring working session)
- Modify: `apps/opps/views.py` (new endpoint)
- Modify: `apps/opps/urls.py`

- [ ] **Step 1: Add endpoint to ensure a working session**

Append to `apps/opps/views.py`:

```python
@api_view(["GET"])
@permission_classes([AllowAny])
def opp_working_session(request, slug: str):
    """Return (or create) the working session for an opp's current run.

    - If the OppWorkspace has a working_session, return its slug.
    - Otherwise, create a new session linked to the opp, attach it, return slug.
    """
    if not request.user.is_authenticated:
        return Response(error_response("auth required", code="auth-required"), status=401)

    try:
        workspace = OppWorkspace.objects.get(slug=slug)
    except OppWorkspace.DoesNotExist:
        # Drive-only opp (pre-migration) — create a lazy workspace row.
        workspace = OppWorkspace.objects.create(
            slug=slug, display_name=slug, created_by=request.user,
        )

    if workspace.working_session is None or workspace.working_session.status != "active":
        from apps.sessions.models import Session
        session = Session.objects.create(
            owner=request.user,
            title=f"{workspace.display_name} — working session",
            backend_kind="cli", status="active", source="web",
            opp_slug=slug,
        )
        workspace.working_session = session
        workspace.save(update_fields=["working_session", "updated_at"])

    return Response(success_response({
        "working_session_slug": workspace.working_session.slug,
    }))
```

Import the model at top:

```python
from apps.opps.models import OppWorkspace
```

Add to `apps/opps/urls.py` (before the `<slug:slug>` pattern to avoid greedy match):

```python
    path("<slug:slug>/working-session", views.opp_working_session, name="opps-working-session"),
```

- [ ] **Step 2: Add API client**

Append to `frontend/src/api/opps.ts`:

```typescript
export interface WorkingSessionResponse {
  working_session_slug: string;
}

export function getWorkingSession(slug: string): Promise<WorkingSessionResponse> {
  return request<WorkingSessionResponse>(`/opps/${encodeURIComponent(slug)}/working-session`);
}
```

- [ ] **Step 3: Extract ChatPanel component**

Create `frontend/src/components/opps/ChatPanel.tsx` that takes a session slug and renders the message list + send box. Copy the core UI from `ChatPage.tsx` (MessageList + SendBox + useSessionSocket hook) minus the page chrome (sidebar, page header, share popover).

```tsx
// frontend/src/components/opps/ChatPanel.tsx
import { useEffect, useState } from "react";

import { getSession } from "@/api/sessions";
import { CliAuthBanner } from "@/components/CliAuthBanner";
import { MessageList } from "@/components/MessageList";
import { PresenceChips } from "@/components/PresenceChips";
import { SendBox } from "@/components/SendBox";
import { useCliAuthStatus } from "@/hooks/useCliAuthStatus";
import { useSessionSocket } from "@/hooks/useSessionSocket";
import type { Session } from "@/api/types";

interface Props {
  slug: string;
}

export function ChatPanel({ slug }: Props) {
  const [meta, setMeta] = useState<Session | null>(null);
  const socket = useSessionSocket(slug);
  const cliConnected = useCliAuthStatus();

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then(setMeta).catch(() => {});
  }, [slug]);

  if (!meta) {
    return <div className="p-4 text-xs text-muted-foreground">Loading chat…</div>;
  }

  return (
    <div className="flex h-full flex-col">
      {!cliConnected && <CliAuthBanner />}
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-[11px]">
        <span className="truncate text-muted-foreground">{meta.title}</span>
        <div className="ml-auto">
          <PresenceChips participants={socket.state.participants ?? []} />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={socket.state.messages ?? []} />
      </div>
      <div className="border-t border-border">
        <SendBox socket={socket} />
      </div>
    </div>
  );
}
```

(If `MessageList` / `SendBox` / `useSessionSocket` have different prop names or APIs, adapt to match the actual components.)

- [ ] **Step 4: Refactor ChatPage to use ChatPanel**

Reduce `ChatPage.tsx` to: sidebar + ChatPanel. The sidebar and the page-level chrome stay; the message-list/send-box portion becomes `<ChatPanel slug={slug} />`. This keeps behavior identical for existing chat pages.

- [ ] **Step 5: Embed ChatPanel in OppWorkbenchPage**

Modify `frontend/src/pages/OppWorkbenchPage.tsx`. Add state for working session slug, fetch on mount, and render a right column:

```tsx
import { ChatPanel } from "@/components/opps/ChatPanel";
import { getWorkingSession } from "@/api/opps";

// Inside the component body:
const [workingSessionSlug, setWorkingSessionSlug] = useState<string | null>(null);
useEffect(() => {
  if (!slug) return;
  getWorkingSession(slug)
    .then((r) => setWorkingSessionSlug(r.working_session_slug))
    .catch(() => setWorkingSessionSlug(null));
}, [slug]);

// In the render:
<div className="flex flex-1 overflow-hidden">
  {/* existing: sidebar + skill list + step detail */}
  <aside className="w-[180px] shrink-0">{/*...*/}</aside>
  <main className="min-w-0 flex-1 overflow-y-auto">{/* SkillList */}</main>
  <section className="w-[440px] shrink-0 border-l border-border overflow-y-auto">
    {/* StepDetailPane */}
  </section>
  <section className="w-[400px] shrink-0 border-l border-border">
    {workingSessionSlug ? (
      <ChatPanel slug={workingSessionSlug} />
    ) : (
      <div className="p-4 text-xs text-muted-foreground">Loading chat…</div>
    )}
  </section>
</div>
```

(Adapt panel widths to existing layout if there's a collapse toggle; keep chat panel behind a toggle for narrow screens if useful.)

- [ ] **Step 6: Type check + smoke test**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0.

Then `docker compose up`. Open an existing opp or create one. Verify the right pane shows the chat, `/auth/cli` banner appears if CLI not connected, draft/presence works.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py frontend/src/api/opps.ts frontend/src/api/types.ts frontend/src/components/opps/ChatPanel.tsx frontend/src/pages/ChatPage.tsx frontend/src/pages/OppWorkbenchPage.tsx
git commit -m "feat(opps): embed ChatPanel in OppWorkbenchPage + opp working-session endpoint"
```

---

## Task 5: Inline artifact rendering (slice 3)

Step detail pane renders markdown/YAML/JSON artifacts inline via MarkdownRenderer instead of linking to Drive.

**Files:**
- Create: `frontend/src/components/opps/ArtifactBody.tsx`
- Modify: `frontend/src/components/opps/StepDetailPane.tsx`

- [ ] **Step 1: Create ArtifactBody component**

```tsx
// frontend/src/components/opps/ArtifactBody.tsx
import { useEffect, useState } from "react";

import { artifactBodyUrl } from "@/api/opps";
import { MarkdownRenderer } from "@/components/MarkdownRenderer";

const MAX_BYTES = 50 * 1024;

interface Props {
  slug: string;
  runId: string;
  skill: string;
  artifactName: string;
  mimeType: string;
  webViewLink?: string;
}

export function ArtifactBody({ slug, runId, skill, artifactName, mimeType, webViewLink }: Props) {
  const [state, setState] = useState<
    { kind: "loading" } |
    { kind: "error"; message: string } |
    { kind: "too-large"; size: number } |
    { kind: "loaded"; content: string; rendered: "markdown" | "code" }
  >({ kind: "loading" });

  useEffect(() => {
    const url = artifactBodyUrl(slug, runId, skill, artifactName);
    fetch(url, { credentials: "include" })
      .then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const content = await r.text();
        if (content.length > MAX_BYTES) {
          setState({ kind: "too-large", size: content.length });
          return;
        }
        const isMd = artifactName.endsWith(".md") || mimeType.startsWith("text/markdown");
        const isYaml = artifactName.endsWith(".yaml") || artifactName.endsWith(".yml");
        const isJson = artifactName.endsWith(".json");
        if (isMd) {
          setState({ kind: "loaded", content, rendered: "markdown" });
        } else if (isYaml || isJson) {
          const lang = isYaml ? "yaml" : "json";
          setState({ kind: "loaded", content: `\`\`\`${lang}\n${content}\n\`\`\``, rendered: "markdown" });
        } else {
          setState({ kind: "loaded", content, rendered: "code" });
        }
      })
      .catch((err) => setState({ kind: "error", message: String(err.message ?? err) }));
  }, [slug, runId, skill, artifactName, mimeType]);

  if (state.kind === "loading") {
    return <div className="p-3 text-xs text-muted-foreground">Loading…</div>;
  }
  if (state.kind === "error") {
    return <div className="p-3 text-xs text-destructive">Error: {state.message}</div>;
  }
  if (state.kind === "too-large") {
    return (
      <div className="p-3 text-xs text-muted-foreground">
        File is {(state.size / 1024).toFixed(1)} KB — too large to render inline.{" "}
        {webViewLink && (
          <a href={webViewLink} target="_blank" rel="noopener noreferrer" className="text-primary underline">
            Open in Drive
          </a>
        )}
      </div>
    );
  }
  if (state.rendered === "markdown") {
    return (
      <div className="p-3">
        <MarkdownRenderer content={state.content} />
      </div>
    );
  }
  return (
    <pre className="overflow-x-auto p-3 font-mono text-xs text-muted-foreground">
      {state.content}
    </pre>
  );
}
```

- [ ] **Step 2: Wire into StepDetailPane**

In `frontend/src/components/opps/StepDetailPane.tsx`, below the artifact list, for the step's first/primary artifact, render `<ArtifactBody ... />`. Leave the list clickable so users can switch which artifact is shown.

Pattern:

```tsx
const [activeArtifact, setActiveArtifact] = useState(step.artifacts[0] ?? null);

// ... artifact list, each row clickable to setActiveArtifact(artifact) ...

{activeArtifact && (
  <div className="mt-3 rounded border border-border">
    <div className="border-b border-border bg-card px-3 py-1.5 font-mono text-[10px] text-muted-foreground">
      {activeArtifact.path}
    </div>
    <ArtifactBody
      slug={slug}
      runId={run.run_id}
      skill={step.skill_name}
      artifactName={activeArtifact.name}
      mimeType={activeArtifact.mime_type}
      webViewLink={activeArtifact.drive_web_link}
    />
  </div>
)}
```

(Pull `slug` and `run` from `useParams()` + props as the existing StepDetailPane does.)

- [ ] **Step 3: Type check + smoke**

Run: `cd frontend && npx tsc --noEmit` → 0.

Open any existing opp with completed steps, click through artifacts. Markdown/YAML/JSON should render inline; large files fall back to Drive link.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/opps/ArtifactBody.tsx frontend/src/components/opps/StepDetailPane.tsx
git commit -m "feat(opps): render artifact bodies inline in StepDetailPane"
```

---

## Task 6: WebSocket broadcast on Drive-modifying turns (slice 4 backend)

Sessions consumer broadcasts an `opp_updated` event after any turn whose tool use touched the Drive MCP.

**Files:**
- Modify: `apps/sessions/consumers.py` (or wherever the turn-complete hook lives)
- Modify: `apps/sessions/turn_driver.py` (to surface the tool-use events)
- Create: `apps/sessions/tests/test_opp_updated_broadcast.py`

- [ ] **Step 1: Write failing test**

```python
# apps/sessions/tests/test_opp_updated_broadcast.py
import pytest
from channels.layers import get_channel_layer

from apps.auth.models import User
from apps.sessions.models import Session
from apps.sessions.opp_broadcast import maybe_emit_opp_updated


@pytest.mark.asyncio
async def test_broadcast_on_drive_tool_use():
    from asgiref.sync import sync_to_async
    user = await sync_to_async(User.objects.create)(email="a@dimagi.com", display_name="A")
    session = await sync_to_async(Session.objects.create)(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
    )
    tool_uses = [{"name": "ace-gdrive:drive_create_file"}]

    layer = get_channel_layer()
    await layer.group_add("opp.malaria-pilot.run-001", "test-channel")

    await maybe_emit_opp_updated(session, tool_uses)

    msg = await layer.receive("test-channel")
    assert msg["type"] == "opp.updated"
    assert msg["opp_slug"] == "malaria-pilot"
    assert msg["run_id"] == "run-001"


@pytest.mark.asyncio
async def test_no_broadcast_for_non_drive_tools():
    from asgiref.sync import sync_to_async
    user = await sync_to_async(User.objects.create)(email="b@dimagi.com", display_name="B")
    session = await sync_to_async(Session.objects.create)(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
    )
    tool_uses = [{"name": "other:some_tool"}]

    layer = get_channel_layer()
    await layer.group_add("opp.malaria-pilot.run-001", "test-channel-2")

    await maybe_emit_opp_updated(session, tool_uses)

    # No message should arrive; give it a moment and check
    import asyncio
    done, pending = await asyncio.wait(
        [asyncio.create_task(layer.receive("test-channel-2"))],
        timeout=0.2,
    )
    assert not done  # nothing received
    for p in pending:
        p.cancel()
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/sessions/tests/test_opp_updated_broadcast.py -v`
Expected: ImportError (module doesn't exist)

- [ ] **Step 3: Implement broadcaster**

```python
# apps/sessions/opp_broadcast.py
"""Broadcast opp.updated events when a chat turn produced Drive side-effects.

Watched by OppWorkbenchPage on the frontend; triggers a refetch of the
opp snapshot. Pragmatic detection: any tool_use event with a name
matching ace-gdrive:drive_* or ace-gdrive:docs_*."""
from __future__ import annotations

from channels.layers import get_channel_layer

from apps.sessions.models import Session


def _touches_drive(tool_uses: list[dict]) -> bool:
    for tu in tool_uses:
        name = tu.get("name", "")
        if name.startswith("ace-gdrive:drive_") or name.startswith("ace-gdrive:docs_"):
            return True
    return False


def _opp_group(slug: str, run_id: str) -> str:
    return f"opp.{slug}.{run_id or 'default'}"


async def maybe_emit_opp_updated(session: Session, tool_uses: list[dict]) -> None:
    """Emit an opp.updated event if session is opp-linked and a Drive tool ran."""
    if not session.opp_slug:
        return
    if not _touches_drive(tool_uses):
        return
    layer = get_channel_layer()
    if layer is None:
        return
    await layer.group_send(
        _opp_group(session.opp_slug, session.opp_run_id or ""),
        {
            "type": "opp.updated",
            "opp_slug": session.opp_slug,
            "run_id": session.opp_run_id or "",
        },
    )
```

- [ ] **Step 4: Wire into the turn lifecycle**

Identify where a turn completes in `apps/sessions/turn_driver.py` or `apps/sessions/consumers.py`. After the assistant turn finishes and tool_use events have been persisted, call `maybe_emit_opp_updated(session, tool_uses)` — where `tool_uses` is the list of tool-use content items from that turn.

Rough injection point (pseudocode — adapt to actual turn_driver):

```python
# In turn_driver.py after the turn completes:
from apps.sessions.opp_broadcast import maybe_emit_opp_updated

tool_uses = [
    item for msg in turn_messages
    for item in (msg.content.get("content", []) if isinstance(msg.content, dict) else [])
    if isinstance(item, dict) and item.get("type") == "tool_use"
]
await maybe_emit_opp_updated(session, tool_uses)
```

Read the existing turn_driver code carefully and add the call at the right place (after the turn is committed, before the consumer broadcasts turn-complete to the session group).

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest apps/sessions/tests/test_opp_updated_broadcast.py -v`
Expected: 2 PASSED

- [ ] **Step 6: Run full suite**

Run: `uv run pytest -q`
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/opp_broadcast.py apps/sessions/turn_driver.py apps/sessions/tests/test_opp_updated_broadcast.py
git commit -m "feat(sessions): broadcast opp_updated event on Drive-modifying turns"
```

---

## Task 7: Workbench WebSocket subscription + refetch (slice 4 frontend)

Workbench subscribes to the opp channel; on `opp_updated`, refetches the opp snapshot.

**Files:**
- Create: `frontend/src/hooks/useOppSocket.ts`
- Create: `apps/sessions/routing.py` update (if needed) — or extend existing URL router
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx`
- Modify: `config/routing.py` (Channels routing — verify opp group consumer exists)

- [ ] **Step 1: Add an OppSocketConsumer**

Create `apps/opps/consumers.py`:

```python
"""WebSocket consumer for the opp workbench. Subscribes to opp.<slug>.<run_id>
group events (currently just opp.updated) and relays to the client.

No incoming messages — this consumer is read-only from the client's POV.
The backend broadcasts events via channel_layer.group_send() from
apps.sessions.opp_broadcast.
"""
from __future__ import annotations

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class OppConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if user is None or not user.is_authenticated:
            await self.close(code=4001)
            return
        self.slug = self.scope["url_route"]["kwargs"]["slug"]
        self.run_id = self.scope["url_route"]["kwargs"].get("run_id", "")
        self.group = f"opp.{self.slug}.{self.run_id or 'default'}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    # Channel layer event handlers (dotted → underscored):
    async def opp_updated(self, event):
        await self.send_json({
            "event": "opp.updated",
            "data": {"slug": event["opp_slug"], "run_id": event["run_id"]},
        })
```

Add to `config/routing.py` (or whichever file holds the Channels URLRouter):

```python
from apps.opps.consumers import OppConsumer

websocket_urlpatterns = [
    # ... existing sessions routes ...
    re_path(
        r"ws/opps/(?P<slug>[^/]+)/runs/(?P<run_id>[^/]+)/$",
        OppConsumer.as_asgi(),
    ),
    re_path(
        r"ws/opps/(?P<slug>[^/]+)/$",
        OppConsumer.as_asgi(),
    ),
]
```

- [ ] **Step 2: Create the frontend hook**

```tsx
// frontend/src/hooks/useOppSocket.ts
import { useEffect, useRef } from "react";

interface Options {
  slug: string;
  runId?: string;
  onOppUpdated?: () => void;
}

const WS_BASE = (() => {
  // Same-origin WS: wss:// for https, ws:// otherwise. Respects /ace prefix via BASE_URL.
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const base = (import.meta.env.BASE_URL ?? "/").replace(/\/$/, "");
  return `${protocol}//${window.location.host}${base}`;
})();

export function useOppSocket({ slug, runId, onOppUpdated }: Options) {
  const handlerRef = useRef(onOppUpdated);
  handlerRef.current = onOppUpdated;

  useEffect(() => {
    if (!slug) return;
    const suffix = runId ? `/runs/${encodeURIComponent(runId)}/` : "/";
    const url = `${WS_BASE}/ws/opps/${encodeURIComponent(slug)}${suffix}`;
    let ws: WebSocket | null = new WebSocket(url);
    let closedByCleanup = false;

    ws.onmessage = (e) => {
      try {
        const { event } = JSON.parse(e.data);
        if (event === "opp.updated") handlerRef.current?.();
      } catch { /* ignore */ }
    };
    ws.onclose = () => {
      if (!closedByCleanup) {
        // Simple reconnect: single retry after 2s. Production could exponential-backoff.
        setTimeout(() => {
          if (closedByCleanup) return;
          ws = new WebSocket(url);
        }, 2000);
      }
    };

    return () => {
      closedByCleanup = true;
      ws?.close();
    };
  }, [slug, runId]);
}
```

- [ ] **Step 3: Subscribe in OppWorkbenchPage**

In `frontend/src/pages/OppWorkbenchPage.tsx`, use the hook:

```tsx
import { useOppSocket } from "@/hooks/useOppSocket";

// Inside component:
useOppSocket({
  slug,
  runId,
  onOppUpdated: () => load(),  // load() is the existing refetch callback
});
```

- [ ] **Step 4: Manual smoke test**

Run `docker compose up`. Open `/opps/<slug>` in one tab. In the chat panel, type a message like "write a test file to Drive" (or trigger a skill). When the turn completes and touches Drive, the workbench should refetch without a page reload — the skill list should update.

- [ ] **Step 5: Commit**

```bash
git add apps/opps/consumers.py config/routing.py frontend/src/hooks/useOppSocket.ts frontend/src/pages/OppWorkbenchPage.tsx
git commit -m "feat(opps): OppConsumer + useOppSocket — auto-refetch workbench on Drive events"
```

---

## Task 8: Action translator endpoint (slice 5 backend)

`POST /api/opps/<slug>/runs/<run_id>/actions/<action>` translates a web action into a chat message injected into the attached session.

**Files:**
- Create: `apps/opps/actions.py`
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_actions.py`

- [ ] **Step 1: Write failing test**

```python
# apps/opps/tests/test_actions.py
import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.sessions.models import Message, Session


@pytest.fixture
def opp(db):
    user = User.objects.create(email="jon@dimagi.com", display_name="Jon")
    session = Session.objects.create(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
        title="Malaria — working",
    )
    workspace = OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria",
        working_session=session, created_by=user,
    )
    return workspace, user


def test_run_action_injects_chat_message(opp, db):
    workspace, user = opp
    c = Client(); c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/run",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 200
    msgs = list(workspace.working_session.messages.order_by("turn_index"))
    assert any("idea-to-pdd" in m.plaintext for m in msgs)
    assert any("run" in m.plaintext.lower() for m in msgs)


def test_approve_action(opp, db):
    workspace, user = opp
    c = Client(); c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/approve",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 200
    latest = workspace.working_session.messages.order_by("-turn_index").first()
    assert "approve" in latest.plaintext.lower()
    assert "idea-to-pdd" in latest.plaintext


def test_reject_action_requires_reason(opp, db):
    workspace, user = opp
    c = Client(); c.force_login(user)
    # Missing reason
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/reject",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 400
    # With reason
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/reject",
        data={"skill": "idea-to-pdd", "reason": "needs more detail"},
        content_type="application/json",
    )
    assert resp.status_code == 200
    latest = workspace.working_session.messages.order_by("-turn_index").first()
    assert "reject" in latest.plaintext.lower()
    assert "needs more detail" in latest.plaintext


def test_unknown_action_returns_400(opp, db):
    workspace, user = opp
    c = Client(); c.force_login(user)
    resp = c.post(
        "/api/opps/malaria-pilot/runs/run-001/actions/nonsense",
        data={"skill": "idea-to-pdd"}, content_type="application/json",
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/opps/tests/test_actions.py -v`
Expected: 404s (endpoint doesn't exist).

- [ ] **Step 3: Implement translator**

```python
# apps/opps/actions.py
"""Translate web actions (Run, Rerun, Approve, Reject) into chat messages
injected into the opp's working session.

Phrasing is centralized here so frontend buttons can change without
touching the prompt wording."""
from __future__ import annotations

from dataclasses import dataclass

from apps.sessions.models import Message, Session


class ActionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ActionPayload:
    skill: str
    reason: str | None = None


def _next_turn_index(session: Session) -> int:
    last = session.messages.order_by("-turn_index").first()
    return (last.turn_index + 1) if last else 0


def _phrase(action: str, slug: str, payload: ActionPayload) -> str:
    if action == "run":
        return f"Run /ace:step {payload.skill} for {slug}."
    if action == "rerun":
        return f"Rerun /ace:step {payload.skill} for {slug}."
    if action == "approve":
        return f"Approve the gate for {payload.skill} in {slug}."
    if action == "reject":
        return (
            f"Reject the gate for {payload.skill} in {slug}. "
            f"Reason: {payload.reason}"
        )
    raise ActionError("unknown-action", f"unknown action {action!r}")


def inject_action(
    *, session: Session, action: str, slug: str, payload: ActionPayload, user
) -> Message:
    if action == "reject" and not payload.reason:
        raise ActionError("reason-required", "reject requires a reason")
    if not payload.skill:
        raise ActionError("skill-required", "action requires a skill name")
    text = _phrase(action, slug, payload)
    return Message.objects.create(
        session=session,
        turn_index=_next_turn_index(session),
        role="user",
        sender_user=user,
        content={"type": "text", "source": "opps-action", "action": action},
        plaintext=text,
        status="complete",
    )
```

- [ ] **Step 4: Add view + URL**

Append to `apps/opps/views.py`:

```python
from apps.opps.actions import ActionError, ActionPayload, inject_action


@api_view(["POST"])
@permission_classes([AllowAny])
def opp_action(request, slug: str, run_id: str, action: str):
    if not request.user.is_authenticated:
        return Response(error_response("auth required", code="auth-required"), status=401)
    try:
        workspace = OppWorkspace.objects.get(slug=slug)
    except OppWorkspace.DoesNotExist:
        return Response(error_response("opp not found", code="opp-not-found"), status=404)
    session = workspace.working_session
    if session is None or session.status != "active":
        return Response(
            error_response("no active working session", code="no-session"), status=409,
        )
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return Response(error_response("invalid JSON", code="bad-json"), status=400)

    payload = ActionPayload(skill=body.get("skill", ""), reason=body.get("reason"))
    try:
        message = inject_action(
            session=session, action=action, slug=slug, payload=payload,
            user=request.user,
        )
    except ActionError as exc:
        status = 400 if exc.code != "unknown-action" else 400
        return Response(error_response(str(exc), code=exc.code), status=status)

    return Response(success_response({
        "message_id": message.id,
        "turn_index": message.turn_index,
    }))
```

Add URL to `apps/opps/urls.py`:

```python
    path(
        "<slug:slug>/runs/<str:run_id>/actions/<str:action>",
        views.opp_action, name="opps-action",
    ),
```

- [ ] **Step 5: Run tests — expect pass**

Run: `uv run pytest apps/opps/tests/test_actions.py -v`
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add apps/opps/actions.py apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_actions.py
git commit -m "feat(opps): POST /actions/<action> — translate web actions to chat messages"
```

---

## Task 9: Action buttons UI (slice 5 frontend)

Context-aware buttons in the StepDetailPane for Run/Rerun/Approve/Reject. Each calls the action endpoint.

**Files:**
- Create: `frontend/src/components/opps/ActionButtons.tsx`
- Create: `frontend/src/components/opps/RejectDialog.tsx`
- Modify: `frontend/src/api/opps.ts`
- Modify: `frontend/src/components/opps/StepDetailPane.tsx`

- [ ] **Step 1: Add API client**

Append to `frontend/src/api/opps.ts`:

```typescript
export interface ActionPayload {
  skill: string;
  reason?: string;
}

export function runAction(
  slug: string, runId: string, action: string, payload: ActionPayload,
): Promise<{ message_id: number; turn_index: number }> {
  return request(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/actions/${action}`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
```

- [ ] **Step 2: Create RejectDialog**

```tsx
// frontend/src/components/opps/RejectDialog.tsx
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  skill: string;
  onOpenChange: (v: boolean) => void;
  onConfirm: (reason: string) => Promise<void>;
}

export function RejectDialog({ open, skill, onOpenChange, onConfirm }: Props) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  async function handle() {
    setBusy(true);
    try {
      await onConfirm(reason);
      setReason("");
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reject {skill} gate</DialogTitle>
        </DialogHeader>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          placeholder="Reason for rejecting…"
          className="w-full rounded border border-border bg-card p-2 text-xs"
        />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="destructive" onClick={handle} disabled={!reason.trim() || busy}>
            Reject
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Create ActionButtons component**

```tsx
// frontend/src/components/opps/ActionButtons.tsx
import { useState } from "react";
import { toast } from "sonner";

import { runAction } from "@/api/opps";
import { Button } from "@/components/ui/button";
import type { Step } from "@/api/types";
import { RejectDialog } from "./RejectDialog";

interface Props {
  slug: string;
  runId: string;
  step: Step;
}

export function ActionButtons({ slug, runId, step }: Props) {
  const [busy, setBusy] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);

  async function call(action: string, payload: { reason?: string } = {}) {
    setBusy(true);
    try {
      await runAction(slug, runId, action, { skill: step.skill_name, ...payload });
      toast.success(`${action} → chat`);
    } catch (e) {
      toast.error(`${action} failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const status = step.status;
  const showRun = status === "pending";
  const showRerun = status === "complete" || status === "error" || status === "judge-fail";
  const showGate = status === "gate-pending";

  if (!showRun && !showRerun && !showGate) return null;

  return (
    <div className="flex gap-2">
      {showRun && <Button size="sm" disabled={busy} onClick={() => call("run")}>Run</Button>}
      {showRerun && <Button size="sm" variant="outline" disabled={busy} onClick={() => call("rerun")}>Rerun</Button>}
      {showGate && (
        <>
          <Button size="sm" disabled={busy} onClick={() => call("approve")}>Approve gate</Button>
          <Button size="sm" variant="destructive" disabled={busy} onClick={() => setRejectOpen(true)}>
            Reject gate
          </Button>
        </>
      )}
      <RejectDialog
        open={rejectOpen} skill={step.skill_name} onOpenChange={setRejectOpen}
        onConfirm={(reason) => call("reject", { reason })}
      />
    </div>
  );
}
```

- [ ] **Step 4: Wire into StepDetailPane**

In `frontend/src/components/opps/StepDetailPane.tsx`, render `<ActionButtons slug={slug} runId={runId} step={step} />` in the header area of the detail pane.

- [ ] **Step 5: Type check**

Run: `cd frontend && npx tsc --noEmit` → 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/opps/ActionButtons.tsx frontend/src/components/opps/RejectDialog.tsx frontend/src/components/opps/StepDetailPane.tsx frontend/src/api/opps.ts
git commit -m "feat(opps): Run/Rerun/Approve/Reject action buttons in StepDetailPane"
```

---

## Task 10: Edit-artifact endpoint (slice 6 backend)

`PUT /api/opps/<slug>/runs/<run_id>/artifacts/<path>` writes updated content to Drive.

**Files:**
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_edit_artifact.py`

- [ ] **Step 1: Write failing test**

```python
# apps/opps/tests/test_edit_artifact.py
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture
def fake_opp():
    return FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "runs": {
                    "run-001": {"steps": {"1-idea-to-pdd": {"output": {"pdd.md": "# Old\n"}}}}
                }
            }
        }
    })


@pytest.fixture
def authed_client(db):
    User.objects.create(email="jon@dimagi.com", display_name="Jon")
    c = Client(); c.force_login(User.objects.get(email="jon@dimagi.com"))
    return c


def test_write_artifact(authed_client, fake_opp):
    ace_id = fake_opp.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake_opp), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = authed_client.put(
            "/api/opps/malaria-pilot/runs/run-001/steps/idea-to-pdd/artifacts/pdd.md",
            data={"content": "# New content\n"},
            content_type="application/json",
        )
    assert resp.status_code == 200
    file_id = fake_opp.file_id("ACE/malaria-pilot/runs/run-001/steps/1-idea-to-pdd/output/pdd.md")
    assert fake_opp.get_content(file_id, "text/markdown").content == "# New content\n"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/opps/tests/test_edit_artifact.py -v`
Expected: 404 (endpoint doesn't exist).

- [ ] **Step 3: Implement view**

Append to `apps/opps/views.py`:

```python
@api_view(["PUT"])
@permission_classes([AllowAny])
def opp_artifact_write(request, slug: str, run_id: str, skill: str, artifact_name: str):
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(error_response("no ACE root", code="ace-root-not-found"), status=404)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return Response(error_response("invalid JSON", code="bad-json"), status=400)
    content = body.get("content")
    if content is None:
        return Response(error_response("content required", code="missing-content"), status=400)

    # Locate the artifact via load_opp
    from apps.opps.sync import load_opp
    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(error_response(f"opp {slug!r} not found", code="opp-not-found"), status=404)
    step_snap = next((s for s in snap.current_run.steps if s.step.skill_name == skill), None)
    if step_snap is None:
        return Response(error_response("step not found", code="step-not-found"), status=404)
    artifact = next((a for a in step_snap.artifacts if a.name == artifact_name), None)
    if artifact is None:
        return Response(error_response("artifact not found", code="artifact-not-found"), status=404)

    client.update_file(artifact.drive_file_id, content=content, mime_type=artifact.mime_type or "text/plain")
    return Response(success_response({"ok": True}))
```

Add URL to `apps/opps/urls.py`:

```python
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>/write",
        views.opp_artifact_write, name="opps-artifact-write",
    ),
```

(Using `/write` suffix to distinguish from the GET artifact_body endpoint which serves raw content.)

Update the test URL to match: `.../artifacts/pdd.md/write`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest apps/opps/tests/test_edit_artifact.py -v`
Expected: 1 PASSED

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_edit_artifact.py
git commit -m "feat(opps): PUT artifact endpoint — write updated content back to Drive"
```

---

## Task 11: Edit artifact dialog (slice 6 frontend)

Pencil-icon button next to artifact paths opens a modal with a textarea and Save button.

**Files:**
- Create: `frontend/src/components/opps/EditArtifactDialog.tsx`
- Modify: `frontend/src/components/opps/StepDetailPane.tsx`
- Modify: `frontend/src/api/opps.ts`

- [ ] **Step 1: API client**

Append to `frontend/src/api/opps.ts`:

```typescript
export function writeArtifact(
  slug: string, runId: string, skill: string, artifactName: string, content: string,
): Promise<{ ok: true }> {
  return request(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}` +
    `/steps/${encodeURIComponent(skill)}/artifacts/${encodeURIComponent(artifactName)}/write`,
    { method: "PUT", body: JSON.stringify({ content }) },
  );
}
```

- [ ] **Step 2: EditArtifactDialog component**

```tsx
// frontend/src/components/opps/EditArtifactDialog.tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { artifactBodyUrl, writeArtifact } from "@/api/opps";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  runId: string;
  skill: string;
  artifactName: string;
}

export function EditArtifactDialog({ open, onOpenChange, slug, runId, skill, artifactName }: Props) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    fetch(artifactBodyUrl(slug, runId, skill, artifactName), { credentials: "include" })
      .then((r) => r.text())
      .then((text) => setContent(text))
      .finally(() => setLoading(false));
  }, [open, slug, runId, skill, artifactName]);

  async function save() {
    setSaving(true);
    try {
      await writeArtifact(slug, runId, skill, artifactName, content);
      toast.success(`${artifactName} saved`);
      onOpenChange(false);
    } catch (e) {
      toast.error(`Save failed: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Edit {artifactName}</DialogTitle>
          <DialogDescription className="font-mono text-xs">
            {slug} / {runId} / {skill}
          </DialogDescription>
        </DialogHeader>
        {loading ? (
          <div className="p-3 text-xs text-muted-foreground">Loading…</div>
        ) : (
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={24}
            className="w-full rounded border border-border bg-card p-3 font-mono text-xs"
          />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>Cancel</Button>
          <Button onClick={save} disabled={loading || saving}>
            {saving ? "Saving…" : "Save to Drive"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Wire into StepDetailPane**

Add a pencil icon button next to each artifact row in the step detail pane that opens `<EditArtifactDialog>`:

```tsx
import { Pencil } from "lucide-react";
import { EditArtifactDialog } from "./EditArtifactDialog";

// State:
const [editing, setEditing] = useState<{ name: string } | null>(null);

// In each artifact row:
<button
  type="button"
  className="opacity-60 hover:opacity-100"
  onClick={() => setEditing({ name: artifact.name })}
>
  <Pencil className="h-3.5 w-3.5" />
</button>

// At the bottom:
{editing && (
  <EditArtifactDialog
    open={editing !== null}
    onOpenChange={(v) => !v && setEditing(null)}
    slug={slug} runId={runId} skill={step.skill_name}
    artifactName={editing.name}
  />
)}
```

- [ ] **Step 4: Type check + smoke**

Run: `cd frontend && npx tsc --noEmit` → 0. Smoke test editing a PDD and verifying the change lands in Drive.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/opps/EditArtifactDialog.tsx frontend/src/components/opps/StepDetailPane.tsx frontend/src/api/opps.ts
git commit -m "feat(opps): edit-artifact dialog — write markdown/YAML back to Drive"
```

---

## Task 12: Fork endpoint (slice 7 backend)

`POST /api/opps/<slug>/runs/<run_id>/fork` creates a new run by copying artifacts upstream of the fork point.

**Files:**
- Create: `apps/opps/fork.py`
- Modify: `apps/opps/views.py`
- Modify: `apps/opps/urls.py`
- Create: `apps/opps/tests/test_fork.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/opps/tests/test_fork.py
from unittest.mock import patch

import pytest
from django.test import Client

from apps.auth.models import User
from apps.opps.models import OppWorkspace
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.sessions.models import Session


@pytest.fixture
def seeded_opp(db):
    user = User.objects.create(email="a@dimagi.com", display_name="A")
    existing_session = Session.objects.create(
        owner=user, opp_slug="malaria-pilot", opp_run_id="run-001",
        backend_kind="cli", status="active", source="web",
    )
    OppWorkspace.objects.create(
        slug="malaria-pilot", display_name="Malaria",
        working_session=existing_session, created_by=user,
    )

    fake = FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "idea.md": "# Initial idea\n",
                "runs": {
                    "run-001": {
                        "state.yaml": "phase: design-review\n",
                        "steps": {
                            "1-idea-to-pdd": {"output": {"pdd.md": "# PDD v1\n"}},
                            "2-pdd-to-learn-app": {"output": {"learn-app-brief.md": "# Brief\n"}},
                        },
                    },
                },
            },
        },
    })
    return user, fake


def test_fork_with_feedback_copies_upstream(seeded_opp):
    user, fake = seeded_opp
    c = Client(); c.force_login(user)
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = c.post(
            "/api/opps/malaria-pilot/runs/run-001/fork",
            data={"from_skill": "pdd-to-learn-app", "mode": "with-feedback", "feedback": "need bigger net"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    body = resp.json()["data"]
    new_run_id = body["new_run_id"]
    assert new_run_id != "run-001"

    # The new run should have a pdd.md (copied) but NOT the learn-app-brief
    # (because pdd-to-learn-app is the forked-from step)
    new_run_tree = f"ACE/malaria-pilot/runs/{new_run_id}"
    assert fake.file_id(f"{new_run_tree}/steps/1-idea-to-pdd/output/pdd.md")
    # learn-app-brief should NOT exist in new run
    assert not fake.exists(f"{new_run_tree}/steps/2-pdd-to-learn-app")

    # New working session seeded with feedback
    new_session_slug = body["working_session_slug"]
    session = Session.objects.get(slug=new_session_slug)
    assert "need bigger net" in list(session.messages.order_by("-turn_index"))[0].plaintext


def test_fork_empty_only_copies_idea(seeded_opp):
    user, fake = seeded_opp
    c = Client(); c.force_login(user)
    ace_id = fake.folder_id("ACE")
    with patch("apps.opps.views.get_drive_client", return_value=fake), \
         patch("apps.opps.views._resolve_ace_root_folder_id", return_value=ace_id):
        resp = c.post(
            "/api/opps/malaria-pilot/runs/run-001/fork",
            data={"from_skill": "idea-to-pdd", "mode": "empty"},
            content_type="application/json",
        )
    assert resp.status_code == 201
    new_run_id = resp.json()["data"]["new_run_id"]
    # No PDD in new run — only the top-level idea.md is inherited
    assert not fake.exists(f"ACE/malaria-pilot/runs/{new_run_id}/steps")
```

(The `FakeDriveClient.exists(path)` helper may not exist — add it alongside file_id/folder_id if needed.)

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest apps/opps/tests/test_fork.py -v`
Expected: FAIL (endpoint doesn't exist).

- [ ] **Step 3: Implement fork logic**

```python
# apps/opps/fork.py
"""Fork a run: create a new run folder, copy artifacts upstream of the
fork point, create a new working session seeded with context."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from apps.opps.drive_client import DriveClient, DriveFile
from apps.opps.models import OppWorkspace
from apps.opps.sync import load_opp
from apps.sessions.models import Message, Session


class ForkError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ForkResult:
    new_run_id: str
    working_session: Session


RUN_ID_RE = re.compile(r"^run-(\d{3})$")


def _next_run_id(existing: list[str]) -> str:
    maxn = 0
    for r in existing:
        m = RUN_ID_RE.match(r)
        if m:
            maxn = max(maxn, int(m.group(1)))
    return f"run-{maxn + 1:03d}"


def fork_run(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    slug: str,
    from_run_id: str,
    from_skill: str,
    mode: str,
    feedback: str | None,
    owner,
) -> ForkResult:
    if mode not in ("with-feedback", "empty"):
        raise ForkError("invalid-mode", f"invalid mode {mode!r}")
    if mode == "with-feedback" and not feedback:
        raise ForkError("feedback-required", "with-feedback requires feedback text")

    # Load the source run so we know the step ordinal and what to copy
    try:
        snap = load_opp(drive, ace_folder_id=ace_root_folder_id, slug=slug, run_id=from_run_id)
    except FileNotFoundError:
        raise ForkError("opp-not-found", f"opp {slug!r} not found")

    # Resolve the fork step's ordinal
    fork_step = next((s for s in snap.current_run.steps if s.step.skill_name == from_skill), None)
    if fork_step is None:
        raise ForkError("step-not-found", f"skill {from_skill!r} not in run {from_run_id}")
    fork_ordinal = fork_step.step.ordinal

    opp_folder_id = snap.opp_folder_id
    # Find runs/ folder
    opp_children = drive.list_files(opp_folder_id)
    runs_folder = next(
        (f for f in opp_children if f.name == "runs" and f.mime_type.endswith("folder")), None,
    )
    if runs_folder is None:
        raise ForkError("no-runs-folder", "runs/ folder not found")
    existing_runs = [f.name for f in drive.list_files(runs_folder.id) if f.mime_type.endswith("folder")]
    new_run_id = _next_run_id(existing_runs)

    # Create new run folder
    new_run_folder = drive.create_folder(runs_folder.id, new_run_id)

    if mode == "with-feedback":
        # Copy step folders whose ordinal < fork_ordinal
        src_run = next((f for f in drive.list_files(runs_folder.id) if f.name == from_run_id), None)
        if src_run is None:
            raise ForkError("src-run-missing", f"run {from_run_id} not found")
        src_steps_folder = next(
            (f for f in drive.list_files(src_run.id) if f.name == "steps" and f.mime_type.endswith("folder")),
            None,
        )
        if src_steps_folder is not None:
            new_steps_folder = drive.create_folder(new_run_folder, "steps")
            for step_folder in drive.list_files(src_steps_folder.id):
                if not step_folder.mime_type.endswith("folder"):
                    continue
                # Expect folder name like "1-idea-to-pdd"
                m = re.match(r"^(\d+)-", step_folder.name)
                if not m:
                    continue
                if int(m.group(1)) >= fork_ordinal:
                    continue
                # Recursively copy the step folder
                _copy_tree_into(drive, step_folder, new_steps_folder)
        # Copy state.yaml if present
        src_state = next((f for f in drive.list_files(src_run.id) if f.name == "state.yaml"), None)
        if src_state:
            content = drive.get_content(src_state.id, src_state.mime_type).content
            drive.upload_file(new_run_folder, "state.yaml", content, src_state.mime_type or "application/yaml")

    # "empty" mode: just an empty new_run_folder (+ state.yaml)
    if mode == "empty":
        state = (
            f"opp: {slug}\n"
            f"mode: review\n"
            f"current_run: {new_run_id}\n"
            f"forked_from: {from_run_id} (empty fork)\n"
        )
        drive.upload_file(new_run_folder, "state.yaml", state, "application/yaml")

    # Create new working session
    with transaction.atomic():
        session = Session.objects.create(
            owner=owner,
            title=f"{slug} — {new_run_id}",
            backend_kind="cli", status="active", source="web",
            opp_slug=slug, opp_run_id=new_run_id,
        )
        seed_system = (
            f"Forked from {from_run_id} at step `{from_skill}` ({mode} fork). "
            f"Inherited artifacts live in the new run."
        )
        Message.objects.create(
            session=session, turn_index=0, role="system",
            sender_user=owner,
            content={"type": "system", "source": "opps-fork"},
            plaintext=seed_system, status="complete",
        )
        if mode == "with-feedback":
            Message.objects.create(
                session=session, turn_index=1, role="user",
                sender_user=owner,
                content={"type": "text", "source": "opps-fork-feedback"},
                plaintext=f"Rerun /ace:step {from_skill} for {slug} with feedback: {feedback}",
                status="complete",
            )
        else:
            Message.objects.create(
                session=session, turn_index=1, role="user",
                sender_user=owner,
                content={"type": "text", "source": "opps-fork-empty"},
                plaintext=f"Run /ace:step idea-to-pdd for {slug} (empty fork from {from_run_id}).",
                status="complete",
            )
        # Repoint the workspace's working_session to the new run's session
        try:
            workspace = OppWorkspace.objects.get(slug=slug)
            workspace.working_session = session
            workspace.save(update_fields=["working_session", "updated_at"])
        except OppWorkspace.DoesNotExist:
            pass

    return ForkResult(new_run_id=new_run_id, working_session=session)


def _copy_tree_into(drive: DriveClient, src: DriveFile, dst_parent_id: str) -> None:
    """Recursively copy src (folder or file) into dst_parent_id, preserving name."""
    if src.mime_type.endswith("folder"):
        new_folder = drive.create_folder(dst_parent_id, src.name)
        for child in drive.list_files(src.id):
            _copy_tree_into(drive, child, new_folder)
    else:
        drive.copy_file(src.id, dst_parent_id, new_name=src.name)
```

- [ ] **Step 4: Add view + URL**

Append to `apps/opps/views.py`:

```python
from apps.opps.fork import ForkError, fork_run


@api_view(["POST"])
@permission_classes([AllowAny])
def opp_fork(request, slug: str, run_id: str):
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(error_response("no ACE root", code="ace-root-not-found"), status=404)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return Response(error_response("invalid JSON", code="bad-json"), status=400)

    try:
        result = fork_run(
            drive=client, ace_root_folder_id=ace_folder_id, slug=slug,
            from_run_id=run_id,
            from_skill=body.get("from_skill", ""),
            mode=body.get("mode", ""),
            feedback=body.get("feedback"),
            owner=request.user,
        )
    except ForkError as exc:
        return Response(error_response(str(exc), code=exc.code), status=400)

    return Response(
        success_response({
            "new_run_id": result.new_run_id,
            "working_session_slug": result.working_session.slug,
        }),
        status=201,
    )
```

Add URL:

```python
    path("<slug:slug>/runs/<str:run_id>/fork", views.opp_fork, name="opps-fork"),
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest apps/opps/tests/test_fork.py -v`
Expected: 2 PASSED (after adding `exists()` helper to FakeDriveClient if needed).

- [ ] **Step 6: Commit**

```bash
git add apps/opps/fork.py apps/opps/views.py apps/opps/urls.py apps/opps/tests/test_fork.py apps/opps/tests/fixtures/fake_drive.py
git commit -m "feat(opps): POST /fork endpoint — create new run with upstream artifacts + seeded session"
```

---

## Task 13: Fork dialog UI (slice 7 frontend)

"Fork from here" button in StepDetailPane → ForkDialog → on submit, navigates to the new run.

**Files:**
- Create: `frontend/src/components/opps/ForkDialog.tsx`
- Modify: `frontend/src/components/opps/StepDetailPane.tsx`
- Modify: `frontend/src/api/opps.ts`

- [ ] **Step 1: API client**

Append to `frontend/src/api/opps.ts`:

```typescript
export interface ForkPayload {
  from_skill: string;
  mode: "with-feedback" | "empty";
  feedback?: string;
}

export interface ForkResponse {
  new_run_id: string;
  working_session_slug: string;
}

export function forkRun(
  slug: string, runId: string, payload: ForkPayload,
): Promise<ForkResponse> {
  return request<ForkResponse>(
    `/opps/${encodeURIComponent(slug)}/runs/${encodeURIComponent(runId)}/fork`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}
```

- [ ] **Step 2: Create ForkDialog**

```tsx
// frontend/src/components/opps/ForkDialog.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { forkRun } from "@/api/opps";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  runId: string;
  skill: string;
}

export function ForkDialog({ open, onOpenChange, slug, runId, skill }: Props) {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"with-feedback" | "empty">("with-feedback");
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const r = await forkRun(slug, runId, {
        from_skill: skill, mode,
        feedback: mode === "with-feedback" ? feedback : undefined,
      });
      toast.success(`Created ${r.new_run_id}`);
      navigate(`/opps/${slug}/runs/${r.new_run_id}`);
    } catch (e) {
      toast.error(`Fork failed: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const canSubmit = !busy && (mode === "empty" || feedback.trim().length > 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Fork from {skill}</DialogTitle>
          <DialogDescription>
            Create a new run of <code className="font-mono">{slug}</code>, inheriting artifacts produced before this step.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <label className="flex items-start gap-2 text-sm">
            <input type="radio" checked={mode === "with-feedback"} onChange={() => setMode("with-feedback")} />
            <div>
              <div>With feedback</div>
              <div className="text-xs text-muted-foreground">
                Inherit upstream artifacts; rerun from this step with feedback applied.
              </div>
            </div>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="radio" checked={mode === "empty"} onChange={() => setMode("empty")} />
            <div>
              <div>Empty</div>
              <div className="text-xs text-muted-foreground">
                Inherit only idea.md; rerun from step 1.
              </div>
            </div>
          </label>
          {mode === "with-feedback" && (
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              rows={4}
              placeholder="What should change about this step's output?"
              className="rounded border border-border bg-card p-2 text-xs"
            />
          )}
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={!canSubmit}>{busy ? "Forking…" : "Fork"}</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Add "Fork from here" button to StepDetailPane**

Alongside the action buttons, add:

```tsx
import { GitBranch } from "lucide-react";
import { ForkDialog } from "./ForkDialog";

const [forkOpen, setForkOpen] = useState(false);

// Button:
<Button size="sm" variant="outline" onClick={() => setForkOpen(true)}>
  <GitBranch className="mr-1.5 h-3.5 w-3.5" />
  Fork from here
</Button>

<ForkDialog
  open={forkOpen} onOpenChange={setForkOpen}
  slug={slug} runId={runId} skill={step.skill_name}
/>
```

- [ ] **Step 4: Type check + smoke**

Run: `cd frontend && npx tsc --noEmit` → 0. Smoke test: fork an opp from phase 2, verify new run appears and navigation works.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/opps/ForkDialog.tsx frontend/src/components/opps/StepDetailPane.tsx frontend/src/api/opps.ts
git commit -m "feat(opps): ForkDialog — fork from step with feedback or empty"
```

---

## Task 14: Run selector + compare UI (slice 8)

Dropdown in WorkbenchHeader listing all runs, with a "Compare runs..." option.

**Files:**
- Create: `frontend/src/components/opps/RunSelector.tsx`
- Create: `frontend/src/components/opps/CompareRunsDialog.tsx`
- Modify: `frontend/src/components/opps/WorkbenchHeader.tsx`

- [ ] **Step 1: RunSelector component**

```tsx
// frontend/src/components/opps/RunSelector.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { ChevronDown, GitCompare } from "lucide-react";
import type { RunSummary } from "@/api/types";
import { CompareRunsDialog } from "./CompareRunsDialog";

interface Props {
  slug: string;
  currentRunId: string;
  runs: RunSummary[];
}

export function RunSelector({ slug, currentRunId, runs }: Props) {
  const navigate = useNavigate();
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline">
            {currentRunId}
            <ChevronDown className="ml-1 h-3.5 w-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          {runs.map((r) => (
            <DropdownMenuItem
              key={r.run_id}
              onSelect={() => navigate(`/opps/${slug}/runs/${r.run_id}`)}
              className={r.run_id === currentRunId ? "font-semibold" : ""}
            >
              <span className="flex-1">{r.run_id}</span>
              <span className="ml-auto text-xs text-muted-foreground">{r.status}</span>
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => setCompareOpen(true)}>
            <GitCompare className="mr-2 h-3.5 w-3.5" />
            Compare runs…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <CompareRunsDialog
        open={compareOpen} onOpenChange={setCompareOpen}
        slug={slug} runs={runs}
      />
    </>
  );
}
```

- [ ] **Step 2: CompareRunsDialog**

```tsx
// frontend/src/components/opps/CompareRunsDialog.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import type { RunSummary } from "@/api/types";

interface Props {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  slug: string;
  runs: RunSummary[];
}

export function CompareRunsDialog({ open, onOpenChange, slug, runs }: Props) {
  const navigate = useNavigate();
  const [fromRun, setFromRun] = useState(runs[1]?.run_id ?? "");
  const [toRun, setToRun] = useState(runs[0]?.run_id ?? "");

  function go() {
    navigate(`/opps/${slug}/compare?from=${fromRun}&to=${toRun}`);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Compare runs</DialogTitle>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <label className="flex flex-col gap-1 text-sm">
            From
            <select value={fromRun} onChange={(e) => setFromRun(e.target.value)}
                    className="rounded border border-border bg-card p-2">
              {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            To
            <select value={toRun} onChange={(e) => setToRun(e.target.value)}
                    className="rounded border border-border bg-card p-2">
              {runs.map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id}</option>)}
            </select>
          </label>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={go} disabled={!fromRun || !toRun || fromRun === toRun}>Compare</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3: Wire into WorkbenchHeader**

In `frontend/src/components/opps/WorkbenchHeader.tsx`, add the run selector:

```tsx
import { RunSelector } from "./RunSelector";

// In JSX where run info is shown:
<RunSelector slug={opp.slug} currentRunId={run.run_id} runs={runs} />
```

- [ ] **Step 4: Type check + smoke**

Run: `cd frontend && npx tsc --noEmit` → 0. Smoke: dropdown lists all runs; clicking a different one navigates; "Compare runs…" opens dialog.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/opps/RunSelector.tsx frontend/src/components/opps/CompareRunsDialog.tsx frontend/src/components/opps/WorkbenchHeader.tsx
git commit -m "feat(opps): RunSelector + CompareRunsDialog in WorkbenchHeader"
```

---

## Task 15: End-to-end Playwright smoke test

One E2E test that exercises the full flow: new opp → approve gate → fork → compare.

**Files:**
- Create: `e2e/tests/opp-lifecycle.spec.ts`

- [ ] **Step 1: Write the test**

```typescript
// e2e/tests/opp-lifecycle.spec.ts
import { test, expect } from "@playwright/test";

import { newAuthedContext } from "../helpers/auth";

test.describe("Opp lifecycle", () => {
  test("create, approve, fork, compare", async ({ browser }) => {
    const { page, context } = await newAuthedContext(
      browser, "opp-lifecycle@dimagi.com", "Lifecycle",
    );

    // 1. Create a new opp
    await page.goto("/ace/opps");
    await page.getByRole("button", { name: "New Opp" }).click();
    const uniqueSlug = `lifecycle-test-${Date.now()}`;
    await page.getByPlaceholder("malaria-pilot-2026").fill(uniqueSlug);
    await page.getByPlaceholder("Malaria Pilot 2026").fill("E2E Lifecycle");
    await page.getByPlaceholder(/Describe the intervention/).fill("E2E test idea body.");
    await page.getByRole("button", { name: "Create opp" }).click();

    // 2. Should land on the workbench with the seeded chat
    await expect(page).toHaveURL(new RegExp(`/ace/opps/${uniqueSlug}`));
    await expect(page.getByText(uniqueSlug)).toBeVisible();

    // The seeded chat contains the first user message
    await expect(page.locator("text=/idea-to-pdd/i").first()).toBeVisible({ timeout: 10_000 });

    await context.close();
  });
});
```

(This is a partial E2E — the test creates an opp and verifies the UI. Full-flow execution through real skills requires `ACE_USE_FAKE_CLI_BACKEND=true` so the e2e env can drive deterministic turns. The fake backend already exists from Phase 3; extend it if needed.)

- [ ] **Step 2: Run the test**

Run: `cd e2e && ./node_modules/.bin/playwright test tests/opp-lifecycle.spec.ts --reporter=line`
Expected: 1 PASSED.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/opp-lifecycle.spec.ts
git commit -m "test(e2e): opp lifecycle smoke — create → chat seeded"
```

---

## Task 16: Deploy + verify on labs

**Files:** (none — workflow runs)

- [ ] **Step 1: Push to main (PR + merge)**

Follow the existing pattern: push the branch, create a PR, squash-merge. Build workflow auto-triggers.

- [ ] **Step 2: Wait for backend build**

```bash
gh run watch $(gh run list --workflow=build-backend.yml --limit 1 --json databaseId -q '.[0].databaseId') --exit-status
```

- [ ] **Step 3: Trigger deploy**

```bash
gh workflow run deploy-labs.yml --ref main -f run_migrations=true
```

(run_migrations=true this time — we added the OppWorkspace table.)

- [ ] **Step 4: Verify**

```bash
curl -s -o /dev/null -w "labs: %{http_code}\n" https://labs.connect.dimagi.com/ace/api/health
```

Open `https://labs.connect.dimagi.com/ace/opps`, click "New Opp", create a test opp, verify the workbench loads with an attached chat, click Run/Approve/Fork, verify each action injects a chat message.

- [ ] **Step 5: Document in CLAUDE.md**

Add a "Web-native opp lifecycle" section to `CLAUDE.md` noting the 8-slice feature set and the attached-chat model. Update the phase table to mark this phase done.

```bash
git add CLAUDE.md
git commit -m "docs: document web-native opp lifecycle in CLAUDE.md"
git push
```
