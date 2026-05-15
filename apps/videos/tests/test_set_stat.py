"""Tests for the set-stat edit op (problem.* and impact[N].*)."""
from io import StringIO

from ruamel.yaml import YAML

from apps.videos import service


def _doc(yaml_text: str):
    y = YAML(typ="rt")
    y.preserve_quotes = True
    return y.load(StringIO(yaml_text))


def test_set_stat_updates_problem_fields():
    doc = _doc("""\
problem:
  big: "29%"
  caption: "old caption"
  source: "NDHS 2018"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "problem",
        "big": "31%", "caption": "new caption",
    })
    assert r.ok, r.message
    assert doc["problem"]["big"] == "31%"
    assert doc["problem"]["caption"] == "new caption"
    assert doc["problem"]["source"] == "NDHS 2018"   # untouched


def test_set_stat_clears_source_when_explicit_empty_string():
    doc = _doc("""\
problem:
  big: "29%"
  caption: "x"
  source: "NDHS 2018"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "problem", "source": "",
    })
    assert r.ok
    assert "source" not in doc["problem"]


def test_set_stat_updates_impact_item_by_index():
    doc = _doc("""\
impact:
  - big: "$320K"
    caption: "grant"
  - big: "2,000"
    caption: "pairs"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "impact[1]",
        "big": "2,500", "caption": "pairs in cohort",
    })
    assert r.ok
    assert doc["impact"][0]["big"] == "$320K"     # untouched
    assert doc["impact"][1]["big"] == "2,500"
    assert doc["impact"][1]["caption"] == "pairs in cohort"


def test_set_stat_rejects_unknown_path():
    doc = _doc("problem: {big: x, caption: y}\n")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "nope", "big": "z",
    })
    assert not r.ok
    assert "path" in r.message.lower()


def test_set_stat_rejects_impact_index_out_of_range():
    doc = _doc("""\
impact:
  - big: "a"
    caption: "b"
""")
    r = service._apply_single_op(doc, {
        "op": "set-stat", "path": "impact[5]", "big": "x",
    })
    assert not r.ok
    assert "range" in r.message.lower() or "index" in r.message.lower()
