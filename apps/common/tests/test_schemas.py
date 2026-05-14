import datetime as dt

from apps.common.schemas import TimestampMixin, UserRefOut


def test_user_ref_round_trip():
    raw = {"id": 42, "email": "alice@example.com", "display_name": "Alice"}
    parsed = UserRefOut.model_validate(raw)
    assert parsed.email == "alice@example.com"
    dumped = parsed.model_dump()
    assert dumped == raw


def test_timestamp_mixin_iso8601():
    when = dt.datetime(2026, 5, 14, 12, 0, tzinfo=dt.UTC)

    class _S(TimestampMixin):
        pass

    s = _S(created_at=when, updated_at=when)
    dumped = s.model_dump(mode="json")
    assert dumped["created_at"].endswith("Z") or "+00:00" in dumped["created_at"]
