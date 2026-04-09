"""No ORM models.

The ACE visualization reads through to Google Drive on every request.
Opp / Run / Step / Artifact / JudgeResult / GateDecision all live in Drive
as YAML / Markdown / JSONL files, not in Postgres. See:
- docs/specs/2026-04-08-ace-opp-visualization-design.md (Section 6)
- memory entry: project_drive_is_source_of_truth.md

If in the future the team decides to add a Postgres cache for latency,
models go in this file. For now it is intentionally empty.
"""
