"""Tests for apps.system.manifest.build_skill_products_map."""
from apps.system.manifest import build_skill_products_map


def test_build_map_groups_paths_by_produced_by():
    entries = [
        {"path": "1-design/idea-to-pdd.md", "produced_by": "idea-to-pdd"},
        {"path": "1-design/pdd-to-work-order.gdoc", "produced_by": "pdd-to-work-order"},
        {"path": "2-scenarios/scenarios.md", "produced_by": "scenarios-and-acceptance"},
    ]
    out = build_skill_products_map(entries)
    assert out == {
        "idea-to-pdd": ["1-design/idea-to-pdd.md"],
        "pdd-to-work-order": ["1-design/pdd-to-work-order.gdoc"],
        "scenarios-and-acceptance": ["2-scenarios/scenarios.md"],
    }


def test_build_map_collects_multi_product_skills():
    entries = [
        {"path": "1-design/a.md", "produced_by": "skill-x"},
        {"path": "1-design/b.md", "produced_by": "skill-x"},
    ]
    out = build_skill_products_map(entries)
    assert out == {"skill-x": ["1-design/a.md", "1-design/b.md"]}


def test_build_map_skips_entries_with_no_producer():
    """Some manifest rows describe inputs, not products — they have no produced_by."""
    entries = [
        {"path": "idea.md"},
        {"path": "1-design/idea-to-pdd.md", "produced_by": "idea-to-pdd"},
    ]
    out = build_skill_products_map(entries)
    assert out == {"idea-to-pdd": ["1-design/idea-to-pdd.md"]}


def test_build_map_skips_entries_with_no_path():
    entries = [
        {"produced_by": "skill-x"},
    ]
    out = build_skill_products_map(entries)
    assert out == {}
