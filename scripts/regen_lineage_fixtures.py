"""Regenerate the frontend decision-lineage fixtures from the backend.

The frontend tests (``frontend/src/components/opps/decisions/lineage/__tests__``)
read real ``GET …/lineage`` payloads. They are built here, by the same
``build_lineage`` + ``shape_for_viewer`` the endpoint runs, from the chains the
backend tests use — so the two suites cannot drift apart. Run from the repo root:

    DJANGO_SETTINGS_MODULE=config.settings.test PYTHONPATH=. \\
        .venv/bin/python scripts/regen_lineage_fixtures.py
"""
from __future__ import annotations

import json
from pathlib import Path

import django

django.setup()

from apps.opps.decision_lineage import build_lineage, shape_for_viewer  # noqa: E402
from apps.opps.tests.test_decision_lineage import _fresh_chain, _spark_chain  # noqa: E402

OUT = Path("frontend/src/components/opps/decisions/lineage/__tests__")

SPARK_IDS = [
    "working-language",
    "learn-latitude-starting-quiz",
    "sol-devices-and-system-of-record-2208",
    "program-reuse-vs-create-spark",
    "connect-latitude-payment-amount-spark",
    "open-question-recording-path-whole-community-group-declines",
]

SPARK_HEADER = """/**
 * Real `GET …/lineage` payloads for spark/spark-facilitator/20261001-2208 (a
 * clone of dimagi-team's run, itself forked twice), built by the backend from
 * the trimmed real decisions.yaml files in `apps/opps/tests/fixtures/lineage/`
 * and trimmed to six decisions. Regenerate rather than hand-edit:
 * `scripts/regen_lineage_fixtures.py`.
 */"""

FRESH_HEADER = """/**
 * `GET …/lineage` payloads for a clone of a FRESH run — the shape of
 * spark/spark-facilitator/20261004-1706 (copied from dimagi-team's independent
 * run, with the Connect rows re-minted as `<id>-dimagi-team` → `<id>`), built
 * from `_fresh_chain()` in `apps/opps/tests/test_decision_lineage.py`.
 * Regenerate rather than hand-edit: `scripts/regen_lineage_fixtures.py`.
 */"""


def _trim(payload: dict, ids: list[str] | None) -> dict:
    if ids is None:
        return payload
    payload["origins"] = {k: payload["origins"][k] for k in ids if k in payload["origins"]}
    payload["histories"] = {
        k: payload["histories"][k] for k in ids if k in payload["histories"]
    }
    return payload


def _write(path: Path, header: str, names: tuple[str, str], chain, ids) -> None:
    core = build_lineage(chain)
    member = _trim(shape_for_viewer(core, member=True, accessible={"spark"},
                                    script_name="/ace"), ids)
    outsider = _trim(shape_for_viewer(core, member=False, accessible=set(),
                                      script_name="/ace"), ids)
    body = "\n".join(
        f"export const {name}: DecisionLineage = {json.dumps(p, indent=2)};"
        for name, p in zip(names, (member, outsider), strict=True)
    )
    path.write_text(
        f'{header}\nimport type {{ DecisionLineage }} from "@/api/lineage";\n\n{body}\n'
    )


if __name__ == "__main__":
    _write(OUT / "sparkLineage.fixture.ts", SPARK_HEADER,
           ("MEMBER_LINEAGE", "OUTSIDER_LINEAGE"), _spark_chain(), SPARK_IDS)
    _write(OUT / "freshCloneLineage.fixture.ts", FRESH_HEADER,
           ("FRESH_CLONE_MEMBER", "FRESH_CLONE_OUTSIDER"), _fresh_chain(), None)
