"""serialize_decision emits the full v4 row shape to the frontend.

The serializer is the wire contract for DecisionsPanel — every field
the panel reads (including the v4 `evidence_basis` / `conflict_signals`)
must appear here, and legacy rows must serialize with safe defaults.
"""
from apps.opps.parsers import Decision
from apps.opps.serializers import serialize_decision


def _decision(**over) -> Decision:
    base = dict(
        id="row-1",
        phase="1-design",
        skill="idea-to-pdd",
        question="How many visit instruments?",
        ai_default="two linked forms",
    )
    base.update(over)
    return Decision(**base)


def test_serialize_emits_evidence_basis_and_conflict_signals():
    d = _decision(
        evidence_basis="conflicting",
        conflict_signals=["visited twice", "one instrument only"],
    )
    out = serialize_decision(d)
    assert out["evidence_basis"] == "conflicting"
    assert out["conflict_signals"] == ["visited twice", "one instrument only"]


def test_serialize_legacy_decision_defaults_evidence_basis_stated():
    out = serialize_decision(_decision())
    assert out["evidence_basis"] == "stated"
    assert out["conflict_signals"] == []


def test_serialize_conflict_signals_is_a_fresh_list():
    """Defensive: the serialized list must not alias the dataclass field
    (so mutating the payload can't corrupt the cached Decision)."""
    signals = ["a", "b"]
    d = _decision(evidence_basis="conflicting", conflict_signals=signals)
    out = serialize_decision(d)
    out["conflict_signals"].append("c")
    assert d.conflict_signals == ["a", "b"]
