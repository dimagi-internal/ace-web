"""apps/opps/output_previews.py — screenshots of a run's outputs.

docs/specs/2026-09-29-output-previews-design.md
"""
from __future__ import annotations

import yaml

from apps.opps.output_previews import (
    attach_previews,
    load_output_previews,
    output_slug,
)
from apps.opps.run_products import build_products
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

RUN = "ACE/opp/runs/r1"


def _client(run_tree: dict) -> FakeDriveClient:
    return FakeDriveClient.from_tree({"ACE": {"opp": {"runs": {"r1": run_tree}}}})


def _set_body(client: FakeDriveClient, path: str, data) -> None:
    body = data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False)
    client._nodes_by_id[client.file_id(path)].body = body


def _load(client: FakeDriveClient) -> list[dict]:
    return load_output_previews(client, client.folder_id(RUN))


def _apps_products() -> list[dict]:
    return build_products(
        {
            "commcare-setup": {
                "apps": {
                    "domain": "ace-demo",
                    "learn": {"hq_app_id": "L1"},
                    "deliver": {"hq_app_id": "D1"},
                }
            }
        },
        phase_order=["commcare-setup"],
    )


# --------------------------------------------------------------------------- #
# output_slug
# --------------------------------------------------------------------------- #
def test_output_slug_matches_the_contract():
    assert output_slug("apps.learn") == "apps-learn"
    assert (
        output_slug("synthetic.workflows.programme_report")
        == "synthetic-workflows-programme-report"
    )
    assert output_slug("Learn_App") == "learn-app"


# --------------------------------------------------------------------------- #
# the v1 index
# --------------------------------------------------------------------------- #
def _indexed_client(extra_items: list[dict] | None = None) -> FakeDriveClient:
    client = _client(
        {
            "3-commcare": {
                "previews": {
                    "apps-learn": {
                        "_previews.yaml": "",
                        "02-modules.png": "b",
                        "01-home.png": "a",
                    }
                }
            }
        }
    )
    folder = f"{RUN}/3-commcare/previews/apps-learn"
    _set_body(
        client,
        f"{folder}/_previews.yaml",
        {
            "schema_version": 1,
            "phase": "commcare-setup",
            "output_key": "apps.learn",
            "captured_by": "app-screenshot-capture",
            "captured_phase": "qa-and-training",
            "items": [
                {"file_id": client.file_id(f"{folder}/01-home.png"), "caption": "Home"},
                {"file_id": client.file_id(f"{folder}/02-modules.png"), "name": "Modules"},
                *(extra_items or []),
            ],
        },
    )
    return client


def test_index_is_read_in_its_own_order_with_captions():
    records = _load(_indexed_client())
    assert len(records) == 1
    rec = records[0]
    assert rec["source"] == "index"
    assert rec["phase"] == "commcare-setup"
    assert rec["output_key"] == "apps.learn"
    assert rec["captured_by"] == "app-screenshot-capture"
    assert rec["slug"] == "apps-learn"
    assert [(i["name"], i["caption"]) for i in rec["items"]] == [
        ("01-home.png", "Home"),
        ("Modules", None),
    ]


def test_an_index_cannot_point_outside_the_run():
    """The viewer serves any preview id it is handed, so the run tree is the
    boundary: an id the run doesn't hold is dropped."""
    records = _load(_indexed_client([{"file_id": "someone-elses-file"}]))
    assert [i["name"] for i in records[0]["items"]] == ["01-home.png", "Modules"]


def test_a_folder_without_an_index_shows_its_images_in_name_order():
    client = _client(
        {
            "7-synthetic": {
                "previews": {
                    "synthetic-workflows-programme-report": {
                        "b.png": "",
                        "a.png": "",
                        "notes.txt": "",
                    }
                }
            }
        }
    )
    [rec] = _load(client)
    assert rec["source"] == "folder"
    assert rec["captured_by"] is None
    assert [i["name"] for i in rec["items"]] == ["a.png", "b.png"]


def test_an_index_written_as_a_google_doc_still_parses():
    """A YAML file saved as a Doc exports every newline as \\r\\n\\r\\n\\r\\n."""
    client = _indexed_client()
    path = f"{RUN}/3-commcare/previews/apps-learn/_previews.yaml"
    node = client._nodes_by_id[client.file_id(path)]
    node.body = node.body.replace("\n", "\r\n\r\n\r\n")
    [rec] = _load(client)
    assert rec["output_key"] == "apps.learn"
    assert len(rec["items"]) == 2


def test_no_previews_is_an_empty_list():
    assert _load(_client({"run_state.yaml": "phases: {}"})) == []


# --------------------------------------------------------------------------- #
# legacy: Phase 6's capture manifest
# --------------------------------------------------------------------------- #
def _legacy_client(manifest_rows) -> FakeDriveClient:
    client = _client(
        {
            "6-qa-and-training": {
                "app-screenshot-capture_manifest.yaml": "",
                "screenshots": {
                    "journey-learn": {"home.png": "", "done.png": ""},
                    "journey-deliver": {"form.png": ""},
                },
            }
        }
    )
    shots = f"{RUN}/6-qa-and-training/screenshots"
    ids = {
        "home": client.file_id(f"{shots}/journey-learn/home.png"),
        "done": client.file_id(f"{shots}/journey-learn/done.png"),
        "form": client.file_id(f"{shots}/journey-deliver/form.png"),
    }
    _set_body(
        client,
        f"{RUN}/6-qa-and-training/app-screenshot-capture_manifest.yaml",
        manifest_rows(ids),
    )
    return client


def test_legacy_flat_captures_group_by_app_and_skip_duplicates():
    client = _legacy_client(
        lambda ids: {
            "captures": [
                {"journey_id": "journey-learn-pass", "step": "home",
                 "file_id": ids["home"], "shows": "Home"},
                {"journey_id": "journey-learn-pass", "step": "done",
                 "file_id": ids["done"], "duplicate_of": "home"},
                {"journey_id": "journey-deliver-submit", "step": "form",
                 "file_id": ids["form"]},
            ]
        }
    )
    records = {r["app"]: r for r in _load(client)}
    assert set(records) == {"learn", "deliver"}
    assert [i["caption"] for i in records["learn"]["items"]] == ["Home"]
    assert records["learn"]["captured_by"] == "app-screenshot-capture"


def test_legacy_journey_grouped_manifest_is_read_too():
    client = _legacy_client(
        lambda ids: {
            "journeys": [
                {"journey_id": "journey-learn-pass",
                 "screenshots": [{"step_name": "home", "file_id": ids["home"]}]},
                {"journey_id": "journey-deliver-submit",
                 "steps": [{"step": "form", "file_id": ids["form"]}]},
            ]
        }
    )
    assert {r["app"] for r in _load(client)} == {"learn", "deliver"}


# --------------------------------------------------------------------------- #
# attach
# --------------------------------------------------------------------------- #
def test_attach_by_output_key_and_phase():
    products = attach_previews(_apps_products(), _load(_indexed_client()))
    by_key = {p["key"]: p for p in products}
    learn = by_key["apps.learn"]["previews"]
    assert [p["caption"] for p in learn] == ["Home", None]
    assert all(p["captured_by"] == "app-screenshot-capture" for p in learn)
    assert by_key["apps.deliver"]["previews"] == []


def test_attach_ignores_a_phase_mismatch():
    records = _load(_indexed_client())
    records[0]["phase"] = "some-other-phase"
    records[0]["slug"] = "nothing-matches"
    products = attach_previews(_apps_products(), records)
    assert all(p["previews"] == [] for p in products)


def test_attach_by_folder_slug_when_there_is_no_index():
    products = build_products(
        {
            "synthetic-data-and-workflows": {
                "synthetic": {
                    "workflows": {"programme_report": {"workflow_id": 1, "run_url": "https://labs/x"}}
                }
            }
        }
    )
    record = {
        "source": "folder",
        "slug": "synthetic-workflows-programme-report",
        "captured_by": None,
        "items": [{"file_id": "f1", "name": "a.png", "caption": None, "mime_type": "image/png"}],
    }
    [product] = attach_previews(products, [record])
    assert [p["file_id"] for p in product["previews"]] == ["f1"]


def test_attach_by_an_alias_the_product_absorbed():
    """The cascade and the workflows map both record the programme report;
    de-duplication keeps the first, and an index naming the second must
    still land on it."""
    products = build_products(
        {
            "synthetic-data-and-workflows": {
                "synthetic": {
                    "cascade": {"programme_report": {"workflow_id": 1, "url": "https://labs/r"}},
                    "workflows": {"programme_report": {"workflow_id": 1, "run_url": "https://labs/r"}},
                }
            }
        }
    )
    assert len(products) == 1
    assert products[0]["aliases"] == ["synthetic.workflows.programme_report"]
    record = {
        "source": "index",
        "phase": "synthetic-data-and-workflows",
        "output_key": "synthetic.workflows.programme_report",
        "slug": "synthetic-workflows-programme-report",
        "captured_by": "ddd-run",
        "items": [{"file_id": "f1", "name": "a.png", "caption": None, "mime_type": "image/png"}],
    }
    [product] = attach_previews(products, [record])
    assert product["previews"][0]["captured_by"] == "ddd-run"


def test_legacy_frames_fill_only_apps_nothing_better_covers():
    legacy = _load(
        _legacy_client(
            lambda ids: {
                "captures": [
                    {"journey_id": "journey-learn-pass", "file_id": ids["home"]},
                    {"journey_id": "journey-deliver-submit", "file_id": ids["form"]},
                ]
            }
        )
    )
    indexed = _load(_indexed_client())
    products = attach_previews(_apps_products(), indexed + legacy)
    by_key = {p["key"]: p for p in products}
    # Learn has a v1 index → its frames, not the legacy ones.
    assert [p["caption"] for p in by_key["apps.learn"]["previews"]] == ["Home", None]
    # Deliver has none → the legacy frame.
    assert [p["name"] for p in by_key["apps.deliver"]["previews"]] == ["form.png"]


def test_legacy_frames_match_the_flat_app_key_shape():
    products = build_products(
        {"commcare-setup": {"learn_app": {"hq_url": "https://www.commcarehq.org/a/d/apps/view/L/"}}}
    )
    record = {
        "source": "legacy",
        "app": "learn",
        "captured_by": "app-screenshot-capture",
        "items": [{"file_id": "f1", "name": "a.png", "caption": None, "mime_type": "image/png"}],
    }
    [product] = attach_previews(products, [record])
    assert len(product["previews"]) == 1


def test_every_product_carries_a_previews_list():
    assert all(p["previews"] == [] for p in attach_previews(_apps_products(), []))


def test_legacy_rows_citing_the_recipe_base_use_the_journeys_own_app():
    """Seen on bednet-check-2-visit/20260907-1126: rows name their journey as
    ``journey: journey-learn`` (the recipe base), and the journey block says
    ``app: learn`` outright."""
    client = _legacy_client(
        lambda ids: {
            "journeys": [
                {"journey_id": "journey-learn-pass", "app": "learn",
                 "recipe_base": "journey-learn"},
                {"journey_id": "journey-x", "app": "deliver", "recipe_base": "journey-x"},
            ],
            "captures": [
                {"step": "home", "journey": "journey-learn", "file_id": ids["home"]},
                {"step": "form", "journey": "journey-x", "file_id": ids["form"]},
            ],
        }
    )
    records = {r["app"]: r for r in _load(client)}
    assert [i["file_id"] for i in records["learn"]["items"]] == [
        client.file_id(f"{RUN}/6-qa-and-training/screenshots/journey-learn/home.png")
    ]
    # "journey-x" says nothing by its name; the journey block's app decides.
    assert len(records["deliver"]["items"]) == 1
