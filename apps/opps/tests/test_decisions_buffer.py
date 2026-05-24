import pytest
from django.core.cache import cache

from apps.opps.decisions_buffer import clear_edits, get_edits, remove_edit, set_edit


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_empty_buffer():
    assert get_edits("opp-1", "run-1") == {}


def test_set_and_get():
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="No",
             editor_email="alice@dimagi.com", editor_name="Alice")
    edits = get_edits("opp-1", "run-1")
    assert "d-001" in edits
    assert edits["d-001"]["new_answer"] == "No"
    assert edits["d-001"]["editor_email"] == "alice@dimagi.com"


def test_set_overwrites():
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="Yes",
             editor_email="alice@dimagi.com", editor_name="Alice")
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="No",
             editor_email="bob@dimagi.com", editor_name="Bob")
    edits = get_edits("opp-1", "run-1")
    assert edits["d-001"]["new_answer"] == "No"
    assert edits["d-001"]["editor_email"] == "bob@dimagi.com"


def test_remove_edit():
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="No",
             editor_email="a@b.com", editor_name="A")
    remove_edit("opp-1", "run-1", row_id="d-001")
    assert get_edits("opp-1", "run-1") == {}


def test_remove_nonexistent_is_noop():
    remove_edit("opp-1", "run-1", row_id="d-999")
    assert get_edits("opp-1", "run-1") == {}


def test_clear_edits():
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="A",
             editor_email="a@b.com", editor_name="A")
    set_edit("opp-1", "run-1", row_id="d-002", new_answer="B",
             editor_email="a@b.com", editor_name="A")
    clear_edits("opp-1", "run-1")
    assert get_edits("opp-1", "run-1") == {}


def test_different_runs_isolated():
    set_edit("opp-1", "run-1", row_id="d-001", new_answer="A",
             editor_email="a@b.com", editor_name="A")
    set_edit("opp-1", "run-2", row_id="d-001", new_answer="B",
             editor_email="a@b.com", editor_name="A")
    assert get_edits("opp-1", "run-1")["d-001"]["new_answer"] == "A"
    assert get_edits("opp-1", "run-2")["d-001"]["new_answer"] == "B"
