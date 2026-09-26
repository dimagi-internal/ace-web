"""``apps.opps.run_products`` — a run's products, flattened for the Phases screen.

The shapes here are the ones ``test_summary.py`` pins from real runs, including
the drifts the summary absorbs (ace#705). The walker must find every product
in them without a per-product reader, and must never surface ``nova_url``.
"""
from __future__ import annotations

import pytest

from apps.opps import run_products


@pytest.fixture(autouse=True)
def _no_attribution(monkeypatch):
    """Default: the plugin attributes nothing. Tests that need it opt in."""
    monkeypatch.setattr("apps.opps.skills.product_producers", lambda phase: None)


FULL = {
    "idea-to-design": {
        "pdd": {"title": "Turmeric Market Survey", "description": "FLWs visit markets.",
                "file_id": "fake-pdd"},
        "work_order": {"file_id": "fake-wo"},
    },
    "commcare-setup": {
        "apps": {
            "learn": {
                "name": "Turmeric — FLW Training",
                "nova_url": "https://commcare.app/build/mFkn",
                "hq_app_id": "d29d",
                "hq_url": "https://www.commcarehq.org/a/connect-ace-prod/apps/view/d29d/",
                "build_status": "success",
            },
            "deliver": {"name": "Turmeric — Vendor Visit", "hq_app_id": "91cf"},
            "domain": "connect-ace-prod",
        },
    },
    "connect-setup": {
        "connect": {
            "program": {"id": "cc8f", "name": "Turmeric — Program",
                        "url": "https://connect.dimagi.com/a/x/program/cc8f/"},
            "opportunity": {"id": "8c46", "name": "Turmeric (2026-05-03)",
                            "deep_link": "https://connect.dimagi.com/a/x/opportunity/8c46/",
                            "start_date": "2026-06-14", "end_date": "2099-08-09"},
            "ace_test_user": {"url": "https://connect.dimagi.com/users/ace"},
            "build_memo": {"file_id": "memo", "title": "Build memo",
                           "web_view_link": "https://docs.google.com/document/d/memo/edit"},
        },
    },
    "ocs-setup": {
        "ocs_chatbot": {"experiment_id": "12027", "public_id": "1fcd", "embed_key": "wDwe",
                        "team_slug": "connect-ace",
                        "admin_url": "https://www.openchatstudio.com/a/connect-ace/chatbots/12027/"},
    },
    "qa-and-training": {
        "training": {
            "deck": {"file_id": "fake-deck", "title": "Training Deck",
                     "web_view_link": "https://docs.google.com/presentation/d/fake-deck/edit"},
            "docs": {"llo_guide": {"file_id": "fake-llo",
                                   "web_view_link": "https://docs.google.com/document/d/fake-llo/edit"}},
        },
    },
    "synthetic-data-and-workflows": {
        "synthetic": {
            "source": {"provider": "ace-run", "labs_synthetic_opp_id": 10054,
                       "dashboards": [{"key": "weekly_review", "par_url": "https://labs/d/1"}]},
            "workflows": {"verification": {"run_url": "https://labs/w/5117"}},
        },
    },
}

ORDER = [
    "idea-to-design", "commcare-setup", "connect-setup", "ocs-setup",
    "qa-and-training", "synthetic-data-and-workflows",
]


def _by_key(items):
    return {i["key"]: i for i in items}


def test_walker_finds_every_product_in_phase_order():
    items = run_products.build_products(FULL, phase_order=ORDER)
    assert [i["key"] for i in items] == [
        "pdd", "work_order",
        "apps.learn", "apps.deliver",
        "connect.program", "connect.opportunity", "connect.build_memo",
        "ocs_chatbot",
        "training.deck", "training.docs.llo_guide",
        "synthetic.source.dashboards.0", "synthetic.workflows.verification",
    ]


def test_kinds_are_inferred_from_key_and_url():
    kinds = {k: i["kind"] for k, i in _by_key(
        run_products.build_products(FULL, phase_order=ORDER)).items()}
    assert kinds == {
        "pdd": "document",
        "work_order": "document",
        "apps.learn": "commcare_app",
        "apps.deliver": "commcare_app",
        "connect.program": "connect_program",
        "connect.opportunity": "connect_opportunity",
        "connect.build_memo": "document",
        "ocs_chatbot": "chatbot",
        "training.deck": "deck",
        "training.docs.llo_guide": "document",
        "synthetic.source.dashboards.0": "dashboard",
        "synthetic.workflows.verification": "dashboard",
    }


def test_app_links_to_hq_never_nova_and_builds_url_from_id_and_domain():
    items = _by_key(run_products.build_products(FULL, phase_order=ORDER))
    learn, deliver = items["apps.learn"], items["apps.deliver"]
    assert learn["url"].startswith("https://www.commcarehq.org/")
    assert "commcare.app" not in str(learn)
    # No hq_url recorded: built from hq_app_id + the apps block's domain.
    assert deliver["url"] == "https://www.commcarehq.org/a/connect-ace-prod/apps/view/91cf/"
    assert {"label": "Build", "value": "success"} in learn["facts"]


def test_titles_fall_back_to_readable_names():
    items = _by_key(run_products.build_products(FULL, phase_order=ORDER))
    assert items["pdd"]["title"] == "Turmeric Market Survey"
    assert items["pdd"]["subtitle"] == "FLWs visit markets."
    assert items["work_order"]["title"] == "Work order"
    assert items["training.docs.llo_guide"]["title"] == "LLO guide"
    assert items["synthetic.source.dashboards.0"]["title"] == "Weekly review"


def test_drive_file_id_is_carried_or_derived_from_the_link():
    items = _by_key(run_products.build_products(FULL, phase_order=ORDER))
    assert items["pdd"]["file_id"] == "fake-pdd"
    assert items["pdd"]["url"] == "https://drive.google.com/open?id=fake-pdd"
    assert items["training.deck"]["file_id"] == "fake-deck"
    assert items["apps.learn"]["file_id"] is None


def test_chatbot_carries_embed_credentials_and_opportunity_its_dates():
    items = _by_key(run_products.build_products(FULL, phase_order=ORDER))
    assert items["ocs_chatbot"]["chatbot"] == {"public_id": "1fcd", "embed_key": "wDwe"}
    assert items["ocs_chatbot"]["url"].startswith("https://www.openchatstudio.com/")
    assert {"label": "Starts", "value": "2026-06-14"} in items["connect.opportunity"]["facts"]


def test_ace_test_user_is_not_a_product():
    keys = [i["key"] for i in run_products.build_products(FULL, phase_order=ORDER)]
    assert not any("ace_test_user" in k for k in keys)


def test_flat_connect_and_learn_app_drift_shapes():
    """ace#705: Connect written flat at the products root; apps as learn_app."""
    items = _by_key(run_products.build_products({
        "connect-setup": {
            "opportunity": {"id": "o1", "url": "https://connect.dimagi.com/a/x/opportunity/o1/"},
            "domain": "flat-domain",
        },
        "commcare-setup": {"learn_app": {"name": "Learn", "hq_app_id": "abc"}},
    }))
    assert items["opportunity"]["kind"] == "connect_opportunity"
    assert items["learn_app"]["kind"] == "commcare_app"
    assert items["learn_app"]["url"] == "https://www.commcarehq.org/a/flat-domain/apps/view/abc/"


def test_duplicates_collapse_to_the_first_seen():
    items = run_products.build_products({
        "idea-to-design": {"pdd": {"file_id": "same"}},
        "connect-setup": {"connect": {"build_memo": {"file_id": "same"}}},
    }, phase_order=["idea-to-design", "connect-setup"])
    assert [i["key"] for i in items] == ["pdd"]


def test_items_without_a_usable_locator_are_dropped():
    assert run_products.build_products({
        "commcare-setup": {"apps": {"learn": {"hq_app_id": "abc"}}},  # no domain anywhere
    }) == []


def test_producer_comes_from_plugin_attribution(monkeypatch):
    monkeypatch.setattr(
        "apps.opps.skills.product_producers",
        lambda phase: {"apps.learn": "pdd-to-learn-app", "apps.deliver": "pdd-to-deliver-app"}
        if phase == "commcare-setup" else None,
    )
    items = _by_key(run_products.build_products(FULL, phase_order=ORDER))
    assert items["apps.learn"]["producer"] == "pdd-to-learn-app"
    assert items["apps.deliver"]["producer"] == "pdd-to-deliver-app"
    assert items["pdd"]["producer"] is None


def test_garbage_input_is_empty_not_an_error():
    assert run_products.build_products(None) == []
    assert run_products.build_products({"x": "not-a-dict", "y": {"z": [1, "a"]}}) == []
