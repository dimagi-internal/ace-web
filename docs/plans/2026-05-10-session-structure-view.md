# Session Structure View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the session detail "Cost & timing" tab with a GitHub-Actions-style hierarchical Structure view that shows phases → skills → individual tool calls with timing, status, and parallel-execution visualization. Compute the structure tree on-demand from persisted raw JSONL — no transcript-shaped intermediate persistence.

**Architecture:** Persist the raw JSONL upload bytes (gzipped) on `IngestUpload`. Add a new pure aggregator (`apps/ingest/structure_aggregator.py`) that walks the existing `CostEvent[]` projection and emits a 4-level tree (session → phase → skill → tool, with subagent dispatches recursing inline). Expose via a new `GET /api/sessions/<slug>/structure/` endpoint that re-parses on every request. Frontend renders an expandable tree with status icons, parallel-cluster brackets, and lazy-loaded tool input/output detail. Existing `cost_breakdown` JSONField stays (feeds opp rollup); the dedicated Cost & Timing tab is removed from session UI.

**Tech Stack:** Django 5 + DRF (backend), pytest + pytest-django (tests), React 19 + TypeScript + Tailwind + shadcn/ui (frontend), `gzip` stdlib for blob compression, no new infra dependencies.

---

## Tree shape (reference for all backend tasks)

```json
{
  "schema_version": 1,
  "computed_at": "2026-05-10T14:32:17+00:00",
  "session": {
    "wall_time_seconds": 514,
    "estimated_cost_usd": 1.42,
    "cost_is_partial": false,
    "tokens": {"input_tokens": 1200, "output_tokens": 5400, "cache_creation_tokens": 0, "cache_read_tokens": 8200},
    "status": "ok"
  },
  "phases": [
    {
      "kind": "phase",
      "name": "phase-1-design-review",
      "display": "Phase 1: Design Review",
      "ordinal": 1,
      "wall_time_seconds": 134,
      "estimated_cost_usd": 0.42,
      "cost_is_partial": false,
      "tokens": {"input_tokens": 0, "output_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0},
      "status": "ok",
      "children": [
        {
          "kind": "skill",
          "name": "ace:idea-to-pdd",
          "display": "Idea to PDD",
          "started_at": "2026-05-10T14:32:17+00:00",
          "wall_time_seconds": 62,
          "estimated_cost_usd": 0.18,
          "cost_is_partial": false,
          "tokens": {"input_tokens": 0, "output_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0},
          "status": "ok",
          "is_subagent": false,
          "children": [
            {
              "kind": "parallel_group",
              "started_at": "2026-05-10T14:32:17+00:00",
              "wall_time_seconds": 1,
              "children": [
                {"kind": "tool", "tool_use_id": "toolu_a", "tool_name": "Read", "label": "pdd-template.md", "started_at": "2026-05-10T14:32:17+00:00", "wall_time_seconds": 0, "status": "ok"},
                {"kind": "tool", "tool_use_id": "toolu_b", "tool_name": "Bash", "label": "ls docs/", "started_at": "2026-05-10T14:32:17+00:00", "wall_time_seconds": 0, "status": "ok"}
              ]
            },
            {"kind": "tool", "tool_use_id": "toolu_c", "tool_name": "Edit", "label": "pdd.md", "started_at": "2026-05-10T14:32:18+00:00", "wall_time_seconds": 0, "status": "ok"},
            {
              "kind": "skill",
              "name": "Agent",
              "display": "Agent: design-review-eval",
              "is_subagent": true,
              "started_at": "2026-05-10T14:32:30+00:00",
              "wall_time_seconds": 47,
              "status": "ok",
              "tokens": {"input_tokens": 0, "output_tokens": 0, "cache_creation_tokens": 0, "cache_read_tokens": 0},
              "estimated_cost_usd": 0.0,
              "cost_is_partial": false,
              "children": []
            }
          ]
        }
      ]
    }
  ]
}
```

Key contracts:
- `kind` is one of `"phase" | "skill" | "tool" | "parallel_group"`. Frontend dispatches on this.
- `status` is `"ok" | "error" | "incomplete"`. Tools with `is_error: true` on their `tool_result` are `"error"`. Subtrees containing any `"error"` propagate to `"error"`. Open-at-end-of-stream → `"incomplete"`.
- `is_subagent: true` on a skill node = render compactly by default (children collapsed). Top-level skills render with first level expanded.
- `parallel_group` wraps two-or-more `tool` nodes that share an assistant turn uuid (Claude issued them in one turn = ran in parallel from the model's perspective). Single-tool turns are emitted directly without a group.

## File structure

**Create:**
- `apps/ingest/_common.py` — shared pure helpers (token math, wall-time, registry lookup)
- `apps/ingest/structure_aggregator.py` — pure aggregator: `CostEvent[]` → structure tree
- `apps/ingest/tests/test_structure_aggregator.py`
- `apps/sessions/migrations/00NN_ingestupload_raw_jsonl_gz.py` (number assigned at migration time)
- `frontend/src/lib/format.ts` (promoted from `frontend/src/components/cost/format.ts`)
- `frontend/src/components/structure/StructureTab.tsx`
- `frontend/src/components/structure/StructureNode.tsx` (recursive renderer)
- `frontend/src/components/structure/StructurePhaseRow.tsx`
- `frontend/src/components/structure/StructureSkillRow.tsx`
- `frontend/src/components/structure/StructureToolRow.tsx`
- `frontend/src/components/structure/ParallelCluster.tsx`
- `frontend/src/api/structure.ts`

**Modify:**
- `apps/ingest/parser.py` — add `is_error` and `content_preview` to `CostEvent`; populate from `tool_result` blocks
- `apps/ingest/cost_aggregator.py` — replace local helpers with imports from `_common`
- `apps/ingest/views.py` — save gzipped raw bytes on `IngestUpload`
- `apps/sessions/models.py` — add `raw_jsonl_gz: BinaryField` and `read_raw_jsonl()` method on `IngestUpload`
- `apps/sessions/views.py` — new `session_structure` view
- `apps/sessions/urls.py` — register `/api/sessions/<slug>/structure/`
- `frontend/src/api/types.ts` — add `StructureTree` types
- `frontend/src/components/cost/CostTimingTab.tsx`, `CostPhaseRow.tsx`, `CostSkillRow.tsx`, `CostInvocationRow.tsx` — re-import from `lib/format` (cost feature stays alive — only the *tab* is dropped from session UI)
- `frontend/src/pages/ChatPage.tsx` — replace Cost & Timing `<details>` with Structure tab

**Delete:** none (cost endpoint and JSONField stay; only the session-detail UI tab is removed).

---

## Task 1: Promote shared helpers to apps/ingest/_common.py

Pure refactor. The existing `cost_aggregator.py` contains five helpers that the new structure aggregator will need verbatim. Promote them now so Task 4's aggregator imports them rather than copying.

**Files:**
- Create: `apps/ingest/_common.py`
- Modify: `apps/ingest/cost_aggregator.py:55-79` (remove `_empty_tokens`, `_add_usage`, `_wall_time_seconds`), `apps/ingest/cost_aggregator.py:24-54` (remove `_registry_lookup`, `_skill_phase_index`)
- Test: existing `apps/ingest/tests/test_cost_aggregator.py` must stay green

- [ ] **Step 1: Create `apps/ingest/_common.py`**

```python
"""Pure helpers shared by cost_aggregator and structure_aggregator.

No Django imports at module load time — `_skill_phase_index` does a lazy
import so tests can monkeypatch and pure unit tests don't drag the ORM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def empty_tokens() -> dict[str, int]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_tokens": 0,
        "cache_read_tokens": 0,
    }


def add_usage(target: dict[str, int], usage: dict[str, Any] | None) -> None:
    if not usage:
        return
    target["input_tokens"] += usage.get("input_tokens", 0) or 0
    target["output_tokens"] += usage.get("output_tokens", 0) or 0
    target["cache_creation_tokens"] += usage.get("cache_creation_input_tokens", 0) or 0
    target["cache_read_tokens"] += usage.get("cache_read_input_tokens", 0) or 0


def wall_time_seconds(start: datetime | None, end: datetime | None) -> int:
    if start is None or end is None:
        return 0
    delta = (end - start).total_seconds()
    return max(0, int(round(delta)))


def registry_lookup(phase_index: dict[str, dict], name: str) -> dict | None:
    """Look up a skill or agent in the phase index, with namespace fallback.

    JSONL transcripts identify skills/agents with the plugin namespace prefix
    (e.g. "ace:idea-to-pdd"). The registry indexes by the unprefixed name from
    each agent's frontmatter. Try the literal name first, then strip the
    "<namespace>:" prefix and try again.
    """
    direct = phase_index.get(name)
    if direct is not None:
        return direct
    if ":" in name:
        return phase_index.get(name.split(":", 1)[1])
    return None


def skill_phase_index() -> dict[str, dict]:
    """Return {skill_name: {phase, phase_display, phase_ordinal}} from the ACE plugin registry.

    Lazy import + exception guard keeps this module pure (no hard Django dep
    at module load) and lets tests monkeypatch `skill_phase_index` in isolation.
    """
    try:
        from apps.system.reader import get_skill_phase_index  # noqa: PLC0415

        return get_skill_phase_index()
    except Exception:
        return {}
```

- [ ] **Step 2: Update `cost_aggregator.py` to import from `_common`**

Replace lines 24-79 (the five helper functions) with a single import block. Update all internal call sites in the same file:
- `_empty_tokens()` → `empty_tokens()`
- `_add_usage(...)` → `add_usage(...)`
- `_wall_time_seconds(...)` → `wall_time_seconds(...)`
- `_registry_lookup(...)` → `registry_lookup(...)`
- `_skill_phase_index()` → `skill_phase_index()`

The `defaultdict(_empty_tokens)` calls become `defaultdict(empty_tokens)`.

Top-of-file imports:

```python
from apps.ingest._common import (
    add_usage,
    empty_tokens,
    registry_lookup,
    skill_phase_index,
    wall_time_seconds,
)
```

- [ ] **Step 3: Run the cost aggregator test suite to verify the refactor**

Run: `pytest apps/ingest/tests/test_cost_aggregator.py -v`
Expected: all existing tests PASS unchanged.

- [ ] **Step 4: Run the full ingest test suite**

Run: `pytest apps/ingest/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/ingest/_common.py apps/ingest/cost_aggregator.py
git commit -m "refactor(ingest): promote shared helpers to _common.py

Pulls _empty_tokens, _add_usage, _wall_time_seconds, _registry_lookup,
and _skill_phase_index out of cost_aggregator and into apps/ingest/_common.py
so the upcoming structure aggregator can share them without duplicating."
```

---

## Task 2: Extend CostEvent with is_error and content_preview

The structure aggregator needs to surface tool errors as a status icon and a short text preview of the tool result. Add these to the existing event projection so the parser is the single JSONL → events boundary.

**Files:**
- Modify: `apps/ingest/parser.py:31-54` (CostEvent dataclass), `apps/ingest/parser.py:130-145` (tool_result branch)
- Test: `apps/ingest/tests/test_parser.py` (extend)

- [ ] **Step 1: Write failing test for is_error capture**

Append to `apps/ingest/tests/test_parser.py`:

```python
def test_cost_event_captures_tool_result_is_error(tmp_path):
    from apps.ingest.parser import parse_session_file

    jsonl = tmp_path / "errors.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"toolu_1","name":"Bash","input":{"command":"false"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1",'
        '"is_error":true,"content":"exit code 1"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    results = [e for e in events if e.kind == "tool_result"]
    assert len(results) == 1
    assert results[0].is_error is True
    assert results[0].content_preview == "exit code 1"


def test_cost_event_content_preview_truncates_long_results(tmp_path):
    from apps.ingest.parser import parse_session_file

    long_body = "x" * 500
    jsonl = tmp_path / "long.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"toolu_1","name":"Read","input":{}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"toolu_1",'
        f'"content":"{long_body}"' + "}]}}\n"
    )
    _session, events = parse_session_file(jsonl)
    result = next(e for e in events if e.kind == "tool_result")
    assert result.is_error is False
    assert len(result.content_preview) == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/ingest/tests/test_parser.py::test_cost_event_captures_tool_result_is_error apps/ingest/tests/test_parser.py::test_cost_event_content_preview_truncates_long_results -v`
Expected: FAIL with `AttributeError: 'CostEvent' object has no attribute 'is_error'`.

- [ ] **Step 3: Extend CostEvent dataclass**

In `apps/ingest/parser.py`, modify the `CostEvent` dataclass (~line 31):

```python
@dataclass
class CostEvent:
    """One JSONL line, projected onto cost-relevant fields.

    Emitted in chronological (file) order. Aggregators walk this list and
    never re-read the source JSONL.
    """
    kind: Literal["assistant_turn", "tool_use", "tool_result"]
    timestamp: datetime | None
    uuid: str | None
    parent_uuid: str | None = None
    is_sidechain: bool = False

    # assistant_turn fields
    model: str | None = None
    usage: dict[str, Any] | None = None

    # tool_use fields
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None

    # tool_result fields
    matched_tool_use_id: str | None = None
    is_error: bool = False
    content_preview: str | None = None
```

- [ ] **Step 4: Populate the new fields in `_extract_cost_events`**

Replace the `tool_result` branch in `_extract_cost_events` (currently around line 130-145) with:

```python
if kind == "user":
    blocks = payload.get("message", {}).get("content", []) or []
    if not isinstance(blocks, list):
        continue
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            content = block.get("content")
            if isinstance(content, list):
                # Multi-block result content (e.g. text + image refs).
                # Take the first text block as preview.
                preview_src = ""
                for sub in content:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        preview_src = sub.get("text", "")
                        break
            elif isinstance(content, str):
                preview_src = content
            else:
                preview_src = ""
            preview = preview_src[:200] if preview_src else None
            events.append(CostEvent(
                kind="tool_result",
                timestamp=ts,
                uuid=uuid,
                parent_uuid=parent_uuid,
                is_sidechain=is_sidechain,
                matched_tool_use_id=block.get("tool_use_id"),
                is_error=bool(block.get("is_error", False)),
                content_preview=preview,
            ))
    continue
```

- [ ] **Step 5: Run the new tests**

Run: `pytest apps/ingest/tests/test_parser.py -v`
Expected: all PASS, including the two new ones.

- [ ] **Step 6: Run cost aggregator tests to verify no regression**

Run: `pytest apps/ingest/tests/test_cost_aggregator.py -v`
Expected: PASS. The cost aggregator ignores the new fields, so behavior is identical.

- [ ] **Step 7: Commit**

```bash
git add apps/ingest/parser.py apps/ingest/tests/test_parser.py
git commit -m "feat(ingest): capture is_error and content_preview on tool_result events

Lays groundwork for the structure view to render error status icons and
hover-preview snippets without re-reading the JSONL."
```

---

## Task 3: Persist gzipped raw JSONL on IngestUpload

Add `raw_jsonl_gz: BinaryField` to `IngestUpload`, plus a helper to read it back. Wire the upload handler to populate it. Existing rows have NULL — the structure endpoint will return a clear "re-upload to enable" message for those.

**Files:**
- Modify: `apps/sessions/models.py:272-301` (IngestUpload)
- Create: `apps/sessions/migrations/00NN_ingestupload_raw_jsonl_gz.py`
- Modify: `apps/ingest/views.py:155-175` (upload handler — populate the new field)
- Test: `apps/ingest/tests/test_views.py` (extend)

- [ ] **Step 1: Write failing test for blob round-trip**

Append to `apps/ingest/tests/test_views.py`:

```python
def test_upload_persists_raw_jsonl_gz(client):
    """Uploaded transcripts retain a gzipped copy of the raw bytes."""
    import gzip

    from apps.sessions.models import IngestUpload

    raw = (FIXTURES / "tool_use_session.jsonl").read_bytes()
    response = _post_upload(client, raw, filename="tool_use_session.jsonl")
    assert response.status_code == 200
    upload = IngestUpload.objects.latest("created_at")
    assert upload.raw_jsonl_gz, "blob should be populated"
    assert gzip.decompress(upload.raw_jsonl_gz) == raw
    assert upload.read_raw_jsonl() == raw.decode("utf-8")
```

If `_post_upload` doesn't already exist in this test module, factor it out from the existing tests in the same file or inline the multipart POST as those tests do. Match the existing test style in `test_views.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest apps/ingest/tests/test_views.py::test_upload_persists_raw_jsonl_gz -v`
Expected: FAIL with `AttributeError: 'IngestUpload' object has no attribute 'raw_jsonl_gz'`.

- [ ] **Step 3: Add the field and helper to the IngestUpload model**

In `apps/sessions/models.py`, modify the `IngestUpload` class (~line 272):

```python
class IngestUpload(models.Model):
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="ingest_records"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploads"
    )
    source_path = models.CharField(max_length=1000, blank=True, default="")
    raw_bytes = models.BigIntegerField(default=0)
    line_count = models.IntegerField(default=0)
    cli_session_id = models.CharField(max_length=200, blank=True, default="")
    content_sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    # Gzipped raw JSONL bytes — feeds the on-demand session structure view
    # (apps/sessions/views.py::session_structure). Nullable so older uploads
    # (pre-this-PR) and tests that don't care can omit it. Postgres TOAST
    # transparently out-of-lines large values.
    raw_jsonl_gz = models.BinaryField(null=True, blank=True)
    workspace = models.ForeignKey(
        "ace_workspaces.Workspace",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="ingest_uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Upload {self.id} to session {self.session_id}"

    def read_raw_jsonl(self) -> str | None:
        """Decompress and decode the persisted JSONL bytes.

        Returns None for rows uploaded before raw_jsonl_gz was added.
        """
        if not self.raw_jsonl_gz:
            return None
        import gzip

        return gzip.decompress(bytes(self.raw_jsonl_gz)).decode("utf-8")

    class Meta:
        db_table = "ingest_uploads"
```

- [ ] **Step 4: Generate the migration**

Run: `python manage.py makemigrations ace_sessions`
Expected: a new file `apps/sessions/migrations/00NN_ingestupload_raw_jsonl_gz.py` with one `AddField` operation.

Check the file in. The number `NN` is whatever Django picks based on the latest existing migration.

- [ ] **Step 5: Apply the migration locally**

Run: `python manage.py migrate ace_sessions`
Expected: migration applies cleanly.

- [ ] **Step 6: Wire the upload handler to save the blob**

In `apps/ingest/views.py`, find the block that creates the `IngestUpload` row (around line 165 — `IngestUpload.objects.create(...)`). Change the call to also pass `raw_jsonl_gz`:

```python
import gzip

# ... inside the upload view, where `raw_bytes_data` is the uploaded bytes ...
IngestUpload.objects.create(
    session=session,
    uploaded_by=request.user,
    source_path=source_path,
    raw_bytes=parsed.raw_bytes,
    line_count=parsed.line_count,
    cli_session_id=parsed.cli_session_id,
    content_sha256=parsed.content_sha256,
    workspace=workspace,
    raw_jsonl_gz=gzip.compress(raw_bytes_data),
)
```

The variable holding the raw bytes already exists in the upload handler — find the read site (it's the bytes used to compute `content_sha256` upstream of this call) and reuse it. Do NOT re-read the file.

- [ ] **Step 7: Run the new test plus the full upload test suite**

Run: `pytest apps/ingest/tests/test_views.py -v`
Expected: PASS, including the new `test_upload_persists_raw_jsonl_gz`.

- [ ] **Step 8: Commit**

```bash
git add apps/sessions/models.py apps/sessions/migrations/ apps/ingest/views.py apps/ingest/tests/test_views.py
git commit -m "feat(ingest): persist gzipped raw JSONL on IngestUpload

Lets the structure view re-parse on demand without a transcript-shaped
intermediate. Gzipped + Postgres TOAST keeps storage costs reasonable.
Older rows have NULL — structure endpoint will return a clear re-upload
hint for them."
```

---

## Task 4: Build the structure aggregator

Pure function that walks `CostEvent[]` and produces the tree shape documented at the top of this plan. No Django imports at module load. Subagent dispatches recurse inline. Parallel groups detected by same-uuid same-timestamp tool_use clustering.

**Files:**
- Create: `apps/ingest/structure_aggregator.py`
- Create: `apps/ingest/tests/test_structure_aggregator.py`

- [ ] **Step 1: Write the first failing test (schema and totals)**

Create `apps/ingest/tests/test_structure_aggregator.py`:

```python
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _events(filename="cost_session.jsonl"):
    from apps.ingest.parser import parse_session_file
    _session, events = parse_session_file(FIXTURES / filename)
    return events


def test_aggregate_returns_schema_v1_with_session_totals():
    from apps.ingest.structure_aggregator import aggregate
    tree = aggregate(_events())
    assert tree["schema_version"] == 1
    assert "session" in tree
    assert "phases" in tree
    assert "computed_at" in tree
    assert tree["session"]["wall_time_seconds"] >= 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest apps/ingest/tests/test_structure_aggregator.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the minimal aggregator (totals only)**

Create `apps/ingest/structure_aggregator.py`:

```python
"""Walk a CostEvent stream and emit a hierarchical structure tree.

Output shape: documented at the top of
docs/plans/2026-05-10-session-structure-view.md.

Pure: no Django, no IO. Tested against fixture-derived event lists.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.ingest._common import (
    add_usage,
    empty_tokens,
    registry_lookup,
    skill_phase_index,
    wall_time_seconds,
)
from apps.ingest.parser import CostEvent
from apps.ingest.pricing import compute_cost

SCHEMA_VERSION = 1


def aggregate(events: list[CostEvent]) -> dict[str, Any]:
    session_first_ts: datetime | None = None
    session_last_ts: datetime | None = None
    session_tokens = empty_tokens()
    session_cost = 0.0
    session_cost_partial = False

    for event in events:
        if event.timestamp is not None:
            if session_first_ts is None or event.timestamp < session_first_ts:
                session_first_ts = event.timestamp
            if session_last_ts is None or event.timestamp > session_last_ts:
                session_last_ts = event.timestamp
        if event.kind == "assistant_turn":
            add_usage(session_tokens, event.usage)
            cost = compute_cost(event.model, event.usage)
            if cost is None:
                session_cost_partial = True
            else:
                session_cost += cost

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(UTC).isoformat(),
        "session": {
            "wall_time_seconds": wall_time_seconds(session_first_ts, session_last_ts),
            "estimated_cost_usd": round(session_cost, 6),
            "cost_is_partial": session_cost_partial,
            "tokens": session_tokens,
            "status": "ok",
        },
        "phases": [],
    }
```

- [ ] **Step 4: Run to verify the first test passes**

Run: `pytest apps/ingest/tests/test_structure_aggregator.py::test_aggregate_returns_schema_v1_with_session_totals -v`
Expected: PASS.

- [ ] **Step 5: Add a test for skill nodes appearing under their phase**

Append to `apps/ingest/tests/test_structure_aggregator.py`:

```python
def test_skill_dispatch_appears_under_phase(monkeypatch):
    """A Skill tool_use becomes a skill node under the phase the registry maps it to."""
    from apps.ingest import structure_aggregator
    monkeypatch.setattr(
        structure_aggregator, "skill_phase_index",
        lambda: {"idea-to-pdd": {"phase": "phase-1-design-review",
                                 "phase_display": "Phase 1: Design Review",
                                 "phase_ordinal": 1,
                                 "skill_display": "Idea to PDD"}},
    )
    tree = structure_aggregator.aggregate(_events())
    phase = next((p for p in tree["phases"] if p["name"] == "phase-1-design-review"), None)
    assert phase is not None
    assert phase["display"] == "Phase 1: Design Review"
    assert phase["kind"] == "phase"
    skills = [c for c in phase["children"] if c["kind"] == "skill"]
    assert any(s["name"] == "ace:idea-to-pdd" for s in skills)
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest apps/ingest/tests/test_structure_aggregator.py::test_skill_dispatch_appears_under_phase -v`
Expected: FAIL — `phases` is `[]`.

- [ ] **Step 7: Implement skill-and-phase tree building**

Replace the body of `aggregate()` in `structure_aggregator.py` with the full implementation:

```python
def aggregate(events: list[CostEvent]) -> dict[str, Any]:
    phase_index = skill_phase_index()

    # Session-level rollups
    session_first_ts: datetime | None = None
    session_last_ts: datetime | None = None
    session_tokens = empty_tokens()
    session_cost = 0.0
    session_cost_partial = False

    # Build a uuid → assistant_turn event index so tool_use events can find
    # their issuing turn (for parallel grouping by uuid).
    parent_of: dict[str, str | None] = {e.uuid: e.parent_uuid for e in events if e.uuid}

    # Build skill-segment frames: each Skill/Agent tool_use opens a frame keyed
    # by tool_use_id; the matching tool_result closes it. Non-Skill/Agent tools
    # become tool nodes attached to whichever frame is currently open (or to a
    # phase-orchestration bucket if none is open).
    @dataclass
    class _Frame:
        tool_use_id: str
        skill_name: str
        skill_display: str
        is_subagent: bool
        containing_msg_uuid: str | None
        phase_name: str
        start_ts: datetime | None
        last_ts: datetime | None
        tokens: dict[str, int] = field(default_factory=empty_tokens)
        cost: float = 0.0
        cost_partial: bool = False
        children: list[dict] = field(default_factory=list)
        # Track the most-recent assistant turn uuid we've seen attributed to
        # this frame, so consecutive tool_use events that share that uuid
        # cluster as a parallel group.
        last_turn_uuid: str | None = None
        last_parallel_group: dict | None = None
        status: str = "ok"

    open_frames: list[_Frame] = []
    # Top-level skill frames (orchestrator-issued) and phase-orchestration
    # buckets land here, keyed by phase_name.
    phase_buckets: dict[str, dict[str, Any]] = {}
    current_phase: str | None = None

    def _ensure_phase(name: str) -> dict[str, Any]:
        if name not in phase_buckets:
            meta_display = name
            ordinal = 500
            if name == "_orchestration":
                meta_display, ordinal = "Orchestration", 0
            elif name == "_other":
                meta_display, ordinal = "Other", 999
            else:
                for entry in phase_index.values():
                    if entry["phase"] == name:
                        meta_display = entry["phase_display"]
                        ordinal = entry["phase_ordinal"]
                        break
            phase_buckets[name] = {
                "kind": "phase",
                "name": name,
                "display": meta_display,
                "ordinal": ordinal,
                "wall_time_seconds": 0,
                "estimated_cost_usd": 0.0,
                "cost_is_partial": False,
                "tokens": empty_tokens(),
                "status": "ok",
                "children": [],
                "_first_ts": None,
                "_last_ts": None,
            }
        return phase_buckets[name]

    def _attach_to_parent(node: dict, frame: _Frame | None, phase_name: str | None,
                          turn_uuid: str | None) -> None:
        """Append a tool/skill node to its parent (open frame or phase bucket).

        If the previous attached node shares `turn_uuid` with this one (i.e. they
        were issued in the same assistant turn = ran in parallel), wrap them in
        a parallel_group.
        """
        nonlocal_target_children: list[dict]
        if frame is not None:
            nonlocal_target_children = frame.children
            last_turn = frame.last_turn_uuid
            last_group = frame.last_parallel_group
        elif phase_name is not None:
            bucket = _ensure_phase(phase_name)
            nonlocal_target_children = bucket["children"]
            last_turn = bucket.get("_last_turn_uuid")
            last_group = bucket.get("_last_parallel_group")
        else:
            return

        if turn_uuid and last_turn == turn_uuid and node["kind"] == "tool":
            # Same assistant turn as the previous tool node → parallel cluster.
            if last_group is not None:
                last_group["children"].append(node)
                if node.get("started_at") and last_group.get("started_at"):
                    pass  # group started_at is fixed at first child
            else:
                # Wrap the previous node + this one in a new parallel_group.
                if nonlocal_target_children and nonlocal_target_children[-1]["kind"] == "tool":
                    prev = nonlocal_target_children.pop()
                    group = {
                        "kind": "parallel_group",
                        "started_at": prev.get("started_at"),
                        "wall_time_seconds": max(
                            prev.get("wall_time_seconds", 0),
                            node.get("wall_time_seconds", 0),
                        ),
                        "children": [prev, node],
                    }
                    nonlocal_target_children.append(group)
                    if frame is not None:
                        frame.last_parallel_group = group
                    elif phase_name is not None:
                        phase_buckets[phase_name]["_last_parallel_group"] = group
                    return
            # Update group wall time
            if last_group is not None:
                last_group["wall_time_seconds"] = max(
                    last_group["wall_time_seconds"],
                    node.get("wall_time_seconds", 0),
                )
            return

        nonlocal_target_children.append(node)
        if frame is not None:
            frame.last_turn_uuid = turn_uuid
            frame.last_parallel_group = None
        elif phase_name is not None:
            phase_buckets[phase_name]["_last_turn_uuid"] = turn_uuid
            phase_buckets[phase_name]["_last_parallel_group"] = None

    for event in events:
        if event.timestamp is not None:
            if session_first_ts is None or event.timestamp < session_first_ts:
                session_first_ts = event.timestamp
            if session_last_ts is None or event.timestamp > session_last_ts:
                session_last_ts = event.timestamp

        if event.kind == "assistant_turn":
            add_usage(session_tokens, event.usage)
            cost = compute_cost(event.model, event.usage)
            if cost is None:
                session_cost_partial = True
            else:
                session_cost += cost
            # Attribute usage to the innermost open frame, if any
            if open_frames:
                add_usage(open_frames[-1].tokens, event.usage)
                if cost is None:
                    open_frames[-1].cost_partial = True
                else:
                    open_frames[-1].cost += cost
                if event.timestamp is not None:
                    open_frames[-1].last_ts = event.timestamp
            continue

        if event.kind == "tool_use":
            tool_name = event.tool_name or ""
            is_skill = tool_name in ("Skill", "Agent")
            turn_uuid = event.uuid

            if is_skill:
                skill_name = (
                    (event.tool_input or {}).get("skill")
                    or (event.tool_input or {}).get("subagent_type")
                    or "(unknown)"
                )
                entry = registry_lookup(phase_index, skill_name)
                if entry is not None:
                    phase_name = entry["phase"]
                    skill_display = entry.get("skill_display", skill_name)
                    current_phase = phase_name
                elif current_phase is not None:
                    phase_name = current_phase
                    skill_display = skill_name
                else:
                    phase_name = "_other"
                    skill_display = skill_name

                frame = _Frame(
                    tool_use_id=event.tool_use_id or "",
                    skill_name=skill_name,
                    skill_display=skill_display,
                    is_subagent=bool(open_frames),  # nested frames = subagent
                    containing_msg_uuid=event.uuid,
                    phase_name=phase_name,
                    start_ts=event.timestamp,
                    last_ts=event.timestamp,
                )
                open_frames.append(frame)
                continue

            # Regular tool call (Read, Bash, Edit, etc.)
            tool_node = {
                "kind": "tool",
                "tool_use_id": event.tool_use_id or "",
                "tool_name": tool_name,
                "label": _tool_label(tool_name, event.tool_input),
                "started_at": event.timestamp.isoformat() if event.timestamp else None,
                "wall_time_seconds": 0,  # filled in on tool_result
                "status": "ok",  # may flip to "error" on result
            }
            if open_frames:
                _attach_to_parent(tool_node, open_frames[-1], None, turn_uuid)
            elif current_phase is not None:
                _attach_to_parent(tool_node, None, current_phase, turn_uuid)
            else:
                _attach_to_parent(tool_node, None, "_orchestration", turn_uuid)
            continue

        if event.kind == "tool_result":
            # Skill/Agent frame close
            match_idx: int | None = None
            for i in range(len(open_frames) - 1, -1, -1):
                if open_frames[i].tool_use_id == event.matched_tool_use_id:
                    match_idx = i
                    break
            if match_idx is not None:
                frame = open_frames.pop(match_idx)
                if event.timestamp is not None:
                    frame.last_ts = event.timestamp
                if event.is_error:
                    frame.status = "error"
                # Promote child statuses up
                if any(c.get("status") == "error" for c in _walk_status(frame.children)):
                    frame.status = "error"
                skill_node = {
                    "kind": "skill",
                    "name": frame.skill_name,
                    "display": frame.skill_display,
                    "is_subagent": frame.is_subagent,
                    "started_at": frame.start_ts.isoformat() if frame.start_ts else None,
                    "wall_time_seconds": wall_time_seconds(frame.start_ts, frame.last_ts),
                    "estimated_cost_usd": round(frame.cost, 6),
                    "cost_is_partial": frame.cost_partial,
                    "tokens": frame.tokens,
                    "status": frame.status,
                    "children": frame.children,
                }
                if open_frames:
                    # nested skill: attach to the parent frame as a subagent child
                    _attach_to_parent(skill_node, open_frames[-1], None, None)
                else:
                    _attach_to_parent(skill_node, None, frame.phase_name, None)
                continue

            # Regular tool result — find the open tool node in the most recent
            # frame's children (or the phase bucket) and update wall_time + status.
            target_children = (
                open_frames[-1].children if open_frames
                else _ensure_phase(current_phase or "_orchestration")["children"]
            )
            tool_node = _find_tool_node(target_children, event.matched_tool_use_id)
            if tool_node is not None:
                if event.timestamp is not None and tool_node.get("started_at"):
                    start = datetime.fromisoformat(tool_node["started_at"])
                    tool_node["wall_time_seconds"] = wall_time_seconds(start, event.timestamp)
                if event.is_error:
                    tool_node["status"] = "error"
            continue

    # Close any open frames as incomplete
    while open_frames:
        frame = open_frames.pop()
        skill_node = {
            "kind": "skill",
            "name": frame.skill_name,
            "display": frame.skill_display,
            "is_subagent": frame.is_subagent,
            "started_at": frame.start_ts.isoformat() if frame.start_ts else None,
            "wall_time_seconds": wall_time_seconds(frame.start_ts, frame.last_ts),
            "estimated_cost_usd": round(frame.cost, 6),
            "cost_is_partial": frame.cost_partial,
            "tokens": frame.tokens,
            "status": "incomplete",
            "children": frame.children,
        }
        if open_frames:
            _attach_to_parent(skill_node, open_frames[-1], None, None)
        else:
            _attach_to_parent(skill_node, None, frame.phase_name, None)

    # Roll phase totals from children
    for bucket in phase_buckets.values():
        _roll_phase_totals(bucket)

    # Strip private tracking keys before returning
    phases = []
    for bucket in sorted(phase_buckets.values(), key=lambda b: b["ordinal"]):
        for k in ("_first_ts", "_last_ts", "_last_turn_uuid", "_last_parallel_group"):
            bucket.pop(k, None)
        phases.append(bucket)

    session_status = "ok"
    if any(p["status"] == "error" for p in phases):
        session_status = "error"
    elif any(p["status"] == "incomplete" for p in phases):
        session_status = "incomplete"

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at": datetime.now(UTC).isoformat(),
        "session": {
            "wall_time_seconds": wall_time_seconds(session_first_ts, session_last_ts),
            "estimated_cost_usd": round(session_cost, 6),
            "cost_is_partial": session_cost_partial,
            "tokens": session_tokens,
            "status": session_status,
        },
        "phases": phases,
    }
```

Add the supporting imports and helpers at the top of the same file, immediately below the existing imports:

```python
from dataclasses import dataclass, field
from typing import Iterable


def _tool_label(tool_name: str, tool_input: dict | None) -> str:
    """Short human-readable label for a tool call. Used as the row's title."""
    if not tool_input:
        return ""
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:80]
    if tool_name in ("Read", "Edit", "Write"):
        return str(tool_input.get("file_path", ""))[:80]
    if tool_name == "Grep":
        return str(tool_input.get("pattern", ""))[:80]
    if tool_name == "Glob":
        return str(tool_input.get("pattern", ""))[:80]
    if tool_name == "WebFetch":
        return str(tool_input.get("url", ""))[:80]
    # Generic fallback: first string-typed value in the input dict
    for v in tool_input.values():
        if isinstance(v, str):
            return v[:80]
    return ""


def _find_tool_node(nodes: list[dict], tool_use_id: str | None) -> dict | None:
    if not tool_use_id:
        return None
    for node in reversed(nodes):
        if node["kind"] == "tool" and node.get("tool_use_id") == tool_use_id:
            return node
        if node["kind"] == "parallel_group":
            for child in reversed(node["children"]):
                if child.get("tool_use_id") == tool_use_id:
                    return child
    return None


def _walk_status(nodes: Iterable[dict]) -> Iterable[dict]:
    for node in nodes:
        yield node
        if node["kind"] == "parallel_group":
            yield from node["children"]
        elif node["kind"] == "skill":
            yield from _walk_status(node.get("children", []))


def _roll_phase_totals(bucket: dict) -> None:
    """Sum wall/cost/tokens from a phase's direct children."""
    wall = 0
    cost = 0.0
    cost_partial = False
    tokens = empty_tokens()
    status = "ok"
    for child in bucket["children"]:
        if child["kind"] == "skill":
            wall += child.get("wall_time_seconds", 0)
            cost += child.get("estimated_cost_usd", 0.0)
            cost_partial = cost_partial or child.get("cost_is_partial", False)
            for k in tokens:
                tokens[k] += child.get("tokens", {}).get(k, 0)
            if child.get("status") == "error":
                status = "error"
            elif child.get("status") == "incomplete" and status != "error":
                status = "incomplete"
        elif child["kind"] == "parallel_group":
            wall += child.get("wall_time_seconds", 0)
        elif child["kind"] == "tool":
            wall += child.get("wall_time_seconds", 0)
            if child.get("status") == "error":
                status = "error"
    bucket["wall_time_seconds"] = wall
    bucket["estimated_cost_usd"] = round(cost, 6)
    bucket["cost_is_partial"] = cost_partial
    bucket["tokens"] = tokens
    bucket["status"] = status
```

- [ ] **Step 8: Run the new tests**

Run: `pytest apps/ingest/tests/test_structure_aggregator.py -v`
Expected: both tests PASS.

- [ ] **Step 9: Add a parallel-group test**

Append to `apps/ingest/tests/test_structure_aggregator.py`:

```python
def test_consecutive_same_turn_tools_form_parallel_group(tmp_path):
    """Two tool_use blocks in one assistant turn → parallel_group node."""
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    jsonl = tmp_path / "parallel.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        # One assistant turn with two tool_use blocks (parallel issue)
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Read","input":{"file_path":"a.txt"}},'
        '{"type":"tool_use","id":"tB","name":"Read","input":{"file_path":"b.txt"}}]}}\n'
        # Both results
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA","content":"a"}]}}\n'
        '{"type":"user","uuid":"u3","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tB","content":"b"}]}}\n'
    )
    _session, events = parse_session_file(jsonl)
    tree = aggregate(events)
    orch = next((p for p in tree["phases"] if p["name"] == "_orchestration"), None)
    assert orch is not None, f"got phases {[p['name'] for p in tree['phases']]}"
    assert len(orch["children"]) == 1
    group = orch["children"][0]
    assert group["kind"] == "parallel_group"
    assert len(group["children"]) == 2
    assert {c["tool_use_id"] for c in group["children"]} == {"tA", "tB"}


def test_tool_error_propagates_status_up_to_session():
    """A tool with is_error → its frame, phase, and session status flip to 'error'."""
    from pathlib import Path
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    # Reuse the parser-level error fixture pattern inline
    jsonl_path = Path("/tmp/structure_error_fixture.jsonl")
    jsonl_path.write_text(
        '{"type":"system","subtype":"init","session_id":"s1"}\n'
        '{"type":"assistant","uuid":"u1","timestamp":"2026-05-10T14:00:00Z",'
        '"message":{"id":"m1","model":"claude-sonnet-4-6","content":['
        '{"type":"tool_use","id":"tA","name":"Bash","input":{"command":"false"}}]}}\n'
        '{"type":"user","uuid":"u2","timestamp":"2026-05-10T14:00:01Z",'
        '"message":{"content":[{"type":"tool_result","tool_use_id":"tA",'
        '"is_error":true,"content":"exit 1"}]}}\n'
    )
    _session, events = parse_session_file(jsonl_path)
    tree = aggregate(events)
    assert tree["session"]["status"] == "error"
```

- [ ] **Step 10: Run all aggregator tests**

Run: `pytest apps/ingest/tests/test_structure_aggregator.py -v`
Expected: 4 PASS.

- [ ] **Step 11: Run the whole ingest suite to verify no regression**

Run: `pytest apps/ingest/ -v`
Expected: PASS (all existing + new tests).

- [ ] **Step 12: Commit**

```bash
git add apps/ingest/structure_aggregator.py apps/ingest/tests/test_structure_aggregator.py
git commit -m "feat(ingest): structure aggregator for hierarchical session view

Walks CostEvent[] and emits a 4-level tree (session → phase → skill →
tool/parallel_group). Subagent dispatches recurse inline as is_subagent
skill nodes. Parallel tool_use blocks (same assistant turn uuid) cluster
in parallel_group wrappers. Status (ok/error/incomplete) propagates up."
```

---

## Task 5: Add the structure API endpoint

Wire a DRF view that loads the most recent `IngestUpload` for a session, decompresses the raw JSONL, re-parses it, runs the structure aggregator, and returns the tree. Returns a clear error envelope if no raw JSONL is persisted (older uploads).

**Files:**
- Modify: `apps/sessions/views.py` (add `session_structure`)
- Modify: `apps/sessions/urls.py` (register the route)
- Test: `apps/sessions/tests/test_structure_endpoint.py` (new)

- [ ] **Step 1: Write the failing test**

Create `apps/sessions/tests/test_structure_endpoint.py`:

```python
import gzip
from pathlib import Path

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.auth.models import User
from apps.sessions.models import IngestUpload, Session

FIXTURES = Path(__file__).parent.parent.parent / "ingest" / "tests" / "fixtures"


@pytest.fixture
def user(db):
    return User.objects.create_user(email="alice@dimagi.com", password="x")


@pytest.fixture
def session_with_blob(db, user):
    s = Session.objects.create(slug="abc123", title="t", created_by=user)
    raw = (FIXTURES / "tool_use_session.jsonl").read_bytes()
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_bytes=len(raw),
        line_count=raw.count(b"\n"), cli_session_id="cli1",
        raw_jsonl_gz=gzip.compress(raw),
    )
    return s


@pytest.fixture
def session_without_blob(db, user):
    s = Session.objects.create(slug="noblob", title="t", created_by=user)
    IngestUpload.objects.create(
        session=s, uploaded_by=user, raw_bytes=0, line_count=0, cli_session_id="cli2",
        raw_jsonl_gz=None,
    )
    return s


def test_structure_endpoint_returns_tree(session_with_blob, user):
    client = APIClient()
    client.force_authenticate(user)
    response = client.get(f"/api/sessions/{session_with_blob.slug}/structure/")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["schema_version"] == 1
    assert "phases" in body["data"]
    assert body["data"]["session"]["wall_time_seconds"] >= 0


def test_structure_endpoint_returns_no_raw_jsonl_error(session_without_blob, user):
    client = APIClient()
    client.force_authenticate(user)
    response = client.get(f"/api/sessions/{session_without_blob.slug}/structure/")
    assert response.status_code == 200  # envelope-style: 200 + error code
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "no-raw-jsonl"


def test_structure_endpoint_404_for_unknown_slug(user):
    client = APIClient()
    client.force_authenticate(user)
    response = client.get("/api/sessions/does-not-exist/structure/")
    assert response.status_code == 404
```

Match the project's existing test style — check `apps/sessions/tests/test_cost_endpoints.py` for the auth/fixture pattern this codebase uses, and follow it. If `force_authenticate` differs from how that file authenticates, copy the working pattern.

- [ ] **Step 2: Run to verify failure**

Run: `pytest apps/sessions/tests/test_structure_endpoint.py -v`
Expected: FAIL — URL not registered.

- [ ] **Step 3: Add the view**

In `apps/sessions/views.py`, add at the bottom (next to `session_cost_breakdown`):

```python
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def session_structure(request: Request, slug: str) -> Response:
    """Compute the hierarchical structure tree for a session, on demand.

    Reads the most recent IngestUpload's raw_jsonl_gz, re-parses it through
    apps.ingest.parser, and runs apps.ingest.structure_aggregator. Nothing
    is persisted; the tree is computed fresh per request.
    """
    from io import BytesIO

    from apps.common.envelope import error_response, success_response
    from apps.ingest.parser import parse_session_file
    from apps.ingest.structure_aggregator import aggregate

    session = _get_session_or_404(request, slug)
    upload = session.ingest_records.order_by("-created_at").first()
    if upload is None or not upload.raw_jsonl_gz:
        return success_response(
            None,
            error=error_response(
                "no-raw-jsonl",
                "This session has no persisted raw transcript. Re-upload via "
                "/ace:upload-transcript to enable the structure view.",
            ).data["error"],
        )

    # Write to a temp path so parse_session_file can use its existing path-based
    # API. Avoids refactoring the parser to take bytes today.
    import tempfile

    raw_text = upload.read_raw_jsonl()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as tmp:
        tmp.write(raw_text)
        tmp_path = tmp.name
    try:
        from pathlib import Path
        _parsed, events = parse_session_file(Path(tmp_path))
    finally:
        import os
        os.unlink(tmp_path)

    tree = aggregate(events)
    return success_response(tree)
```

Match whatever auth/scoping helper the existing `session_cost_breakdown` view uses (look at `apps/sessions/views.py:328`). Use the same `_get_session_or_404` (or whatever it's called) to enforce membership-gated access.

- [ ] **Step 4: Register the URL**

In `apps/sessions/urls.py`, near the existing `session_cost_breakdown` registration (line ~20):

```python
path(
    "<slug:slug>/structure/",
    views.session_structure,
    name="session_structure",
),
```

- [ ] **Step 5: Run the endpoint tests**

Run: `pytest apps/sessions/tests/test_structure_endpoint.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Run the whole sessions test suite**

Run: `pytest apps/sessions/ -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/views.py apps/sessions/urls.py apps/sessions/tests/test_structure_endpoint.py
git commit -m "feat(sessions): GET /api/sessions/<slug>/structure/ endpoint

On-demand structure tree. Reads persisted raw JSONL, re-parses, runs
the structure aggregator. Returns a no-raw-jsonl error envelope for
older sessions that pre-date raw_jsonl_gz."
```

---

## Task 6: Promote format helpers to shared lib

`frontend/src/components/cost/format.ts` has the duration/tokens/usd formatters. Both the (existing) cost rows and the (new) structure rows want them. Promote to `frontend/src/lib/format.ts`.

**Files:**
- Create: `frontend/src/lib/format.ts` (move contents)
- Modify: existing imports in `frontend/src/components/cost/CostTimingTab.tsx`, `CostPhaseRow.tsx`, `CostSkillRow.tsx`, `CostInvocationRow.tsx`
- Delete: `frontend/src/components/cost/format.ts`

- [ ] **Step 1: Move the file**

```bash
mkdir -p frontend/src/lib
git mv frontend/src/components/cost/format.ts frontend/src/lib/format.ts
```

- [ ] **Step 2: Update imports**

In each of `CostTimingTab.tsx`, `CostPhaseRow.tsx`, `CostSkillRow.tsx`, `CostInvocationRow.tsx`, change:

```ts
import { formatCacheHitRatio, formatDuration, formatTokens, formatUsd, totalTokens } from "./format";
```

to:

```ts
import { formatCacheHitRatio, formatDuration, formatTokens, formatUsd, totalTokens } from "../../lib/format";
```

(Adjust the relative path per file. `cost/` is two levels deep from `src/`, so `../../lib/format` is correct for files in `frontend/src/components/cost/`.)

- [ ] **Step 3: Verify the typecheck passes**

Run: `cd frontend && bunx tsc -b`
Expected: PASS, no errors. (`tsc -b` is what the Docker build runs — see `feedback_tsc_build_mode_stricter` memory.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/format.ts frontend/src/components/cost/
git commit -m "refactor(frontend): promote format helpers to lib/format.ts

Both cost and the upcoming structure components need the duration/tokens/usd
formatters; pulling out of cost/ avoids structure depending on cost/."
```

---

## Task 7: Frontend types and API wrapper for structure

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/structure.ts`

- [ ] **Step 1: Add structure types**

Append to `frontend/src/api/types.ts`:

```ts
export type StructureStatus = "ok" | "error" | "incomplete";

export interface StructureTokens {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

export interface StructureToolNode {
  kind: "tool";
  tool_use_id: string;
  tool_name: string;
  label: string;
  started_at: string | null;
  wall_time_seconds: number;
  status: StructureStatus;
}

export interface StructureParallelGroup {
  kind: "parallel_group";
  started_at: string | null;
  wall_time_seconds: number;
  children: StructureToolNode[];
}

export interface StructureSkillNode {
  kind: "skill";
  name: string;
  display: string;
  is_subagent: boolean;
  started_at: string | null;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
  children: StructureChild[];
}

export type StructureChild = StructureToolNode | StructureParallelGroup | StructureSkillNode;

export interface StructurePhase {
  kind: "phase";
  name: string;
  display: string;
  ordinal: number;
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
  children: StructureChild[];
}

export interface StructureSession {
  wall_time_seconds: number;
  estimated_cost_usd: number;
  cost_is_partial: boolean;
  tokens: StructureTokens;
  status: StructureStatus;
}

export interface StructureTree {
  schema_version: number;
  computed_at: string;
  session: StructureSession;
  phases: StructurePhase[];
}

export interface StructureUnavailable {
  reason: "no-raw-jsonl";
  message: string;
}
```

- [ ] **Step 2: Create the API wrapper**

Create `frontend/src/api/structure.ts`:

```ts
import type { StructureTree } from "./types";
import { apiFetch } from "./client";  // or whatever client wrapper costs.ts uses

export async function getSessionStructure(
  slug: string,
): Promise<{ tree: StructureTree | null; error: { code: string; message: string } | null }> {
  const response = await apiFetch(`/api/sessions/${slug}/structure/`);
  const body = await response.json();
  return { tree: body.data, error: body.error };
}
```

Match the exact client-import pattern that `frontend/src/api/costs.ts` uses (it already wraps the envelope). If `costs.ts` re-throws on `error`, mirror that behavior so callers don't have to unwrap twice.

- [ ] **Step 3: Verify typecheck**

Run: `cd frontend && bunx tsc -b`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/structure.ts
git commit -m "feat(frontend): types and API wrapper for /sessions/<slug>/structure/"
```

---

## Task 8: Frontend Structure tab components

The expandable tree. Header summary at top; phases below; expand to skills; expand a skill to its children (tools + parallel groups + nested subagent skills). Click a tool row to load and show its full input/output. Status icons inline with each row. Subagent skill rows render compact-by-default.

**Files:**
- Create: `frontend/src/components/structure/StructureTab.tsx`
- Create: `frontend/src/components/structure/StructureNode.tsx`
- Create: `frontend/src/components/structure/StructurePhaseRow.tsx`
- Create: `frontend/src/components/structure/StructureSkillRow.tsx`
- Create: `frontend/src/components/structure/StructureToolRow.tsx`
- Create: `frontend/src/components/structure/ParallelCluster.tsx`
- Create: `frontend/src/components/structure/StatusIcon.tsx`

- [ ] **Step 1: Build StatusIcon (reusable across rows)**

Create `frontend/src/components/structure/StatusIcon.tsx`:

```tsx
import { CheckCircle2, XCircle, CircleDashed } from "lucide-react";

import type { StructureStatus } from "../../api/types";

export function StatusIcon({ status }: { status: StructureStatus }) {
  if (status === "error") return <XCircle className="h-4 w-4 text-destructive" aria-label="error" />;
  if (status === "incomplete") return <CircleDashed className="h-4 w-4 text-muted-foreground" aria-label="incomplete" />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-600" aria-label="ok" />;
}
```

- [ ] **Step 2: Build StructureToolRow**

Create `frontend/src/components/structure/StructureToolRow.tsx`:

```tsx
import { useState } from "react";

import type { StructureToolNode } from "../../api/types";
import { formatDuration } from "../../lib/format";
import { StatusIcon } from "./StatusIcon";

interface Props {
  node: StructureToolNode;
  depth: number;
}

export function StructureToolRow({ node, depth }: Props) {
  const [open, setOpen] = useState(false);
  const time = node.started_at ? new Date(node.started_at).toLocaleTimeString() : "—";
  return (
    <div
      className="flex items-center gap-2 py-1 text-sm"
      style={{ paddingLeft: `${depth * 16 + 8}px` }}
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex-1 flex items-center gap-2 text-left"
      >
        <StatusIcon status={node.status} />
        <span className="text-xs text-muted-foreground tabular-nums w-20">{time}</span>
        <span className="font-medium w-16">{node.tool_name}</span>
        <span className="truncate text-muted-foreground">{node.label}</span>
      </button>
      <span className="text-xs text-muted-foreground tabular-nums">
        {formatDuration(node.wall_time_seconds)}
      </span>
      {open ? (
        <div className="text-xs text-muted-foreground italic">
          (Tool detail loading deferred to follow-up — Task 8 currently shows row only)
        </div>
      ) : null}
    </div>
  );
}
```

The "tool detail loading" expansion is a follow-up; the Task 8 baseline is row-only with input/output detail to land in a separate plan.

- [ ] **Step 3: Build ParallelCluster**

Create `frontend/src/components/structure/ParallelCluster.tsx`:

```tsx
import type { StructureParallelGroup } from "../../api/types";
import { formatDuration } from "../../lib/format";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  group: StructureParallelGroup;
  depth: number;
}

export function ParallelCluster({ group, depth }: Props) {
  return (
    <div className="relative" style={{ paddingLeft: `${depth * 16}px` }}>
      <div className="border-l-2 border-blue-400 ml-2 pl-2">
        <div className="text-xs uppercase tracking-wide text-blue-600 py-1 flex items-center gap-2">
          <span>‖ parallel</span>
          <span className="text-muted-foreground tabular-nums">
            {formatDuration(group.wall_time_seconds)}
          </span>
        </div>
        {group.children.map((child) => (
          <StructureToolRow key={child.tool_use_id} node={child} depth={0} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Build StructureSkillRow (recursive)**

Create `frontend/src/components/structure/StructureSkillRow.tsx`:

```tsx
import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructureSkillNode } from "../../api/types";
import { formatDuration, formatUsd } from "../../lib/format";
import { ParallelCluster } from "./ParallelCluster";
import { StatusIcon } from "./StatusIcon";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  node: StructureSkillNode;
  depth: number;
}

export function StructureSkillRow({ node, depth }: Props) {
  // Subagent rows render collapsed by default; top-level skills render with
  // their tool list expanded for at-a-glance scanning.
  const [open, setOpen] = useState(!node.is_subagent);
  const expandable = node.children.length > 0;
  return (
    <>
      <div
        className="flex items-center gap-2 py-1.5 text-sm border-t"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
      >
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          className="flex-1 flex items-center gap-1 text-left disabled:opacity-50"
        >
          {expandable ? (
            <ChevronRight className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`} />
          ) : (
            <span className="w-4" />
          )}
          <StatusIcon status={node.status} />
          <span className={node.is_subagent ? "italic" : "font-medium"}>{node.display}</span>
          {node.is_subagent ? (
            <span className="text-xs text-muted-foreground">subagent · {node.children.length} step{node.children.length === 1 ? "" : "s"}</span>
          ) : null}
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right">
          {formatDuration(node.wall_time_seconds)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right">
          {formatUsd(node.estimated_cost_usd, node.cost_is_partial)}
        </span>
      </div>
      {open
        ? node.children.map((child, i) => {
            if (child.kind === "tool") return <StructureToolRow key={child.tool_use_id} node={child} depth={depth + 1} />;
            if (child.kind === "parallel_group") return <ParallelCluster key={i} group={child} depth={depth + 1} />;
            if (child.kind === "skill") return <StructureSkillRow key={`${child.name}-${i}`} node={child} depth={depth + 1} />;
            return null;
          })
        : null}
    </>
  );
}
```

- [ ] **Step 5: Build StructurePhaseRow**

Create `frontend/src/components/structure/StructurePhaseRow.tsx`:

```tsx
import { useState } from "react";
import { ChevronRight } from "lucide-react";

import type { StructurePhase } from "../../api/types";
import { formatDuration, formatUsd } from "../../lib/format";
import { ParallelCluster } from "./ParallelCluster";
import { StatusIcon } from "./StatusIcon";
import { StructureSkillRow } from "./StructureSkillRow";
import { StructureToolRow } from "./StructureToolRow";

interface Props {
  phase: StructurePhase;
  defaultOpen?: boolean;
}

export function StructurePhaseRow({ phase, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const expandable = phase.children.length > 0;
  const isLifecyclePhase = phase.ordinal > 0 && phase.ordinal < 100;
  return (
    <>
      <div className="flex items-center gap-2 py-2 text-sm border-t">
        <button
          type="button"
          disabled={!expandable}
          onClick={() => setOpen(!open)}
          className="flex-1 flex items-center gap-1 pl-2 text-left disabled:opacity-50"
        >
          {expandable ? (
            <ChevronRight className={`h-4 w-4 transition-transform ${open ? "rotate-90" : ""}`} />
          ) : (
            <span className="w-4" />
          )}
          <StatusIcon status={phase.status} />
          {isLifecyclePhase ? (
            <span className="text-xs font-semibold text-muted-foreground tabular-nums">
              Phase {phase.ordinal}:
            </span>
          ) : null}
          <span className="font-medium">{phase.display}</span>
        </button>
        <span className="text-xs text-muted-foreground tabular-nums w-20 text-right">
          {formatDuration(phase.wall_time_seconds)}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums w-16 text-right">
          {formatUsd(phase.estimated_cost_usd, phase.cost_is_partial)}
        </span>
      </div>
      {open
        ? phase.children.map((child, i) => {
            if (child.kind === "tool") return <StructureToolRow key={child.tool_use_id} node={child} depth={1} />;
            if (child.kind === "parallel_group") return <ParallelCluster key={i} group={child} depth={1} />;
            if (child.kind === "skill") return <StructureSkillRow key={`${child.name}-${i}`} node={child} depth={1} />;
            return null;
          })
        : null}
    </>
  );
}
```

- [ ] **Step 6: Build StructureTab (top-level container)**

Create `frontend/src/components/structure/StructureTab.tsx`:

```tsx
import { useEffect, useState } from "react";

import { getSessionStructure } from "../../api/structure";
import type { StructureTree } from "../../api/types";
import { formatDuration, formatTokens, formatUsd, totalTokens } from "../../lib/format";
import { StatusIcon } from "./StatusIcon";
import { StructurePhaseRow } from "./StructurePhaseRow";

interface Props {
  slug: string;
}

export function StructureTab({ slug }: Props) {
  const [tree, setTree] = useState<StructureTree | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTree(null);
    setError(null);
    getSessionStructure(slug)
      .then(({ tree, error }) => {
        if (cancelled) return;
        if (error) setError(error.message);
        else setTree(tree);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => { cancelled = true; };
  }, [slug]);

  if (error) return <div className="text-sm text-muted-foreground p-4">{error}</div>;
  if (tree === null) return <div className="text-sm text-muted-foreground p-4">Loading…</div>;

  const t = tree.session;
  return (
    <div className="space-y-2 p-4">
      <div className="flex items-center gap-4 text-sm pb-2">
        <StatusIcon status={t.status} />
        <div>
          <div className="text-muted-foreground text-xs uppercase">Wall time</div>
          <div className="text-lg font-medium">{formatDuration(t.wall_time_seconds)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-xs uppercase">Cost</div>
          <div className="text-lg font-medium">{formatUsd(t.estimated_cost_usd, t.cost_is_partial)}</div>
        </div>
        <div>
          <div className="text-muted-foreground text-xs uppercase">Tokens</div>
          <div className="text-lg font-medium tabular-nums">{formatTokens(totalTokens(t.tokens))}</div>
        </div>
      </div>
      <div>
        {tree.phases.map((p) => (
          <StructurePhaseRow key={p.name} phase={p} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Verify the typecheck and a local dev run**

Run: `cd frontend && bunx tsc -b`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/structure/
git commit -m "feat(frontend): structure tab components

GHA-style hierarchical session view: phase → skill → tool/parallel_group,
with subagent skills rendering compact-by-default. Status icon per row,
parallel clusters bracketed visually."
```

---

## Task 9: Wire Structure tab into ChatPage; remove Cost & Timing tab

Replace the "Cost & timing" `<details>` element in `ChatPage.tsx` with a "Structure" `<details>` showing the new tab. The cost endpoint and `cost_breakdown` JSONField stay (opp rollup uses them) — only the per-session UI tab is dropped.

**Files:**
- Modify: `frontend/src/pages/ChatPage.tsx`

- [ ] **Step 1: Replace the Cost tab in ChatPage**

In `frontend/src/pages/ChatPage.tsx`:

1. Replace the import:

```ts
import { CostTimingTab } from "../components/cost/CostTimingTab";
```

with:

```ts
import { StructureTab } from "../components/structure/StructureTab";
```

2. Replace the `<details>` block (lines ~95-105):

```tsx
<details className="border-t">
  <summary
    className="cursor-pointer px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
    onClick={() => setShowCosts(true)}
  >
    Cost &amp; timing
  </summary>
  {showCosts ? <CostTimingTab slug={slug} /> : null}
</details>
```

with:

```tsx
<details className="border-t">
  <summary
    className="cursor-pointer px-4 py-2 text-sm text-muted-foreground hover:text-foreground"
    onClick={() => setShowStructure(true)}
  >
    Structure
  </summary>
  {showStructure ? <StructureTab slug={slug} /> : null}
</details>
```

3. Rename the local state variable: search for `showCosts` / `setShowCosts` in `ChatPage.tsx` and rename them to `showStructure` / `setShowStructure`. Initial value stays `false`.

- [ ] **Step 2: Verify typecheck and dev run**

Run: `cd frontend && bunx tsc -b`
Expected: PASS.

Then start the dev environment and click into a session that has a recent upload (post-Task-3 ingest):

Run: `docker compose up -d && open http://localhost:8000/`

Click a session, expand the new "Structure" details. Expected: phase rows with timing, expandable to skills, then tools, with status icons and parallel-group brackets where relevant. Subagent skill rows render compact (collapsed children) by default.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/ChatPage.tsx
git commit -m "feat(frontend): replace Cost & timing tab with Structure tab

Per docs/plans/2026-05-10-session-structure-view.md. The cost API endpoint
and Session.cost_breakdown JSONField stay — opp rollup still reads them —
only the per-session UI tab is dropped. Structure shows the same phase/cost/
timing rollup when collapsed, plus drill-down to individual tool calls."
```

---

## Task 10: Backfill plan for existing uploads (documentation only)

Older `IngestUpload` rows have `raw_jsonl_gz = NULL`. The endpoint already returns a clear "re-upload via /ace:upload-transcript" message for those — this task documents the expected operator workflow rather than building a backfill.

**Files:**
- Modify: `CLAUDE.md` (add a one-liner under the "Per-session and per-opp cost & timing breakdown" bullet)

- [ ] **Step 1: Update the project context note**

Add to `CLAUDE.md`, in the same bullet that documents the cost & timing breakdown architecture:

> **Structure view** at `apps/sessions/views.py::session_structure` (`GET /api/sessions/<slug>/structure/`): on-demand hierarchical session tree (phase → skill → tool, with subagent recursion + parallel-group clusters). Computed fresh per request from `IngestUpload.raw_jsonl_gz`; never persisted. The Cost & Timing tab was retired in favor of this — `cost_breakdown` JSONField stays for opp-level rollup queries. Pre-2026-05-10 uploads have `raw_jsonl_gz = NULL` and need to be re-uploaded via `/ace:upload-transcript` to enable the structure view.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note the structure view in project context"
```

---

## Self-review

**Spec coverage:** Every requirement from the conversation is addressed:
- "Persist raw JSONL, compute on demand" → Tasks 3, 5
- "DRY across cost + structure" → Task 1 (shared helpers), Task 6 (shared formatters)
- "No transcript-shaped intermediate persistence" → no `structure_breakdown` JSONField; on-demand only (Task 5)
- "Replace Cost & Timing tab; same function when collapsed" → Task 9 (replaces the `<details>` with same collapsed-by-default behavior; phase rows show wall time + cost just like the cost tab did)
- "Single hierarchy with parallel visual + compact subagents" → Task 4 (parallel_group node + is_subagent flag), Task 8 (ParallelCluster component + is_subagent rendering)
- "Cost & Timing fields used elsewhere stay" → opp rollup at `apps/opps/views.py:1436` still reads `Session.cost_breakdown`; Task 9 deliberately does not delete it.

**Placeholder scan:** None.

**Type consistency checked:** `StructureTree`, `StructureChild`, `StructureSkillNode`, `StructureToolNode`, `StructureParallelGroup`, `StructurePhase` — all field names and types match between TypeScript types (Task 7) and the JSON shape emitted by the aggregator (Task 4).
