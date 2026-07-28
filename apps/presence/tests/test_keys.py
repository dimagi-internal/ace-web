"""Page-key parsing is the security boundary — it runs on client input.

These are pure-function tests (no DB, no Redis, no Channels) so the charset
contract is pinned independently of the consumer that consumes it. The
constants here are a CROSS-APP contract: canopy-web's presence keys module
carries the identical values and the two must be changed together.
"""
from apps.presence.keys import (
    GLOBAL_SENTINEL,
    MAX_PAGE_KEY_LEN,
    group_name,
    parse_page_key,
)


class TestWellFormedKeys:
    def test_a_plain_key_parses(self):
        assert parse_page_key("ace:dimagi-team:activity") == (
            "ace",
            "dimagi-team",
            "activity",
        )

    def test_the_resource_may_contain_colons(self):
        assert parse_page_key("ace:ws:opp:bednet/run-001") == (
            "ace",
            "ws",
            "opp:bednet/run-001",
        )

    def test_segments_are_whitespace_stripped(self):
        assert parse_page_key("ace: ws :activity") == ("ace", "ws", "activity")

    def test_the_global_sentinel_is_accepted_as_a_workspace(self):
        assert parse_page_key(f"ace:{GLOBAL_SENTINEL}:settings") == (
            "ace",
            GLOBAL_SENTINEL,
            "settings",
        )

    def test_underscores_and_digits_are_legal_slugs(self):
        assert parse_page_key("ace:team_2:x") == ("ace", "team_2", "x")


class TestRejectedKeys:
    def test_empty(self):
        assert parse_page_key("") is None

    def test_too_few_segments(self):
        assert parse_page_key("junk") is None
        assert parse_page_key("ace:ws") is None

    def test_empty_segments(self):
        assert parse_page_key("::") is None
        assert parse_page_key("ace::activity") is None
        assert parse_page_key("ace:ws:") is None

    def test_an_over_long_key_is_rejected(self):
        """Without a cap the resource segment is unbounded, so one frame
        could push an arbitrarily large key name into Redis. `sub_location`
        was already capped at 120; the key itself was not."""
        assert parse_page_key("ace:ws:" + "a" * MAX_PAGE_KEY_LEN) is None
        # ...and a key of exactly the limit still parses.
        filler = "a" * (MAX_PAGE_KEY_LEN - len("ace:ws:"))
        assert parse_page_key(f"ace:ws:{filler}") == ("ace", "ws", filler)

    def test_an_app_segment_with_illegal_characters_is_rejected(self):
        assert parse_page_key("ACE:ws:x") is None
        assert parse_page_key("ace_web:ws:x") is None
        assert parse_page_key("a" * 33 + ":ws:x") is None

    def test_a_workspace_slug_with_illegal_characters_is_rejected(self):
        """Slugs are unvalidated at CREATION time (Workspace.slug is a bare
        CharField), so the charset is enforced here instead."""
        assert parse_page_key("ace:Acme:x") is None  # uppercase
        assert parse_page_key("ace:acme eu:x") is None  # space
        assert parse_page_key("ace:-acme:x") is None  # leading hyphen
        assert parse_page_key("ace:acme.eu:x") is None  # dot
        assert parse_page_key("ace:" + "a" * 65 + ":x") is None  # over 64 chars

    def test_a_slug_shaped_like_the_sentinel_is_rejected(self):
        """`~` is exactly what WORKSPACE_RE forbids — that is what makes the
        sentinel un-shadowable by any slug that survives this parse."""
        assert GLOBAL_SENTINEL.startswith("~")
        assert parse_page_key("ace:~globa1:x") is None
        assert parse_page_key("ace:~:x") is None


class TestGroupName:
    def test_distinct_keys_never_collide(self):
        assert group_name("ace:a:b:c") != group_name("ace:a:b/c")

    def test_the_name_is_channels_legal(self):
        import re

        assert re.fullmatch(r"[A-Za-z0-9._-]{1,100}", group_name("ace:ws:opp:a/run-1"))
