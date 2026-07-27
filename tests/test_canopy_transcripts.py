"""apps.canopy.transcripts — pulling a turn's raw JSONL back from canopy.

Half of this module is ordinary unit tests over a mocked `urlopen`. The other
half runs against a REAL local HTTP server, because the bug this client exists
to prevent is invisible to a mock: canopy stores a turn's transcript as
CONCATENATED MULTI-MEMBER gzip, and an HTTP client that inflates the response
itself returns only the FIRST member — a 200, no exception, silently short
content, and therefore a silently wrong cost number. Mocking `urlopen` mocks
away exactly the layer where that happens, so the multi-member tests below
speak HTTP for real and one of them demonstrates the truncation empirically
with `httpx` next to our client's behaviour on the same bytes.
"""

import gzip
import io
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest
from django.test import override_settings

from apps.canopy import transcripts

ENABLED = dict(CANOPY_BASE_URL="http://canopy.test", CANOPY_APP_CREDENTIAL="c")


class _Stream(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def getheader(self, name, default=None):
        return self.headers.get(name, default)


def _urlopen(data, headers=None):
    return mock.patch(
        "apps.canopy.transcripts.urllib.request.urlopen",
        return_value=_Stream(data, headers),
    )


@override_settings(**ENABLED)
def test_fetches_plaintext_ndjson_verbatim():
    body = b'{"type":"system"}\n{"type":"assistant"}\n'
    with _urlopen(body) as opened:
        out = transcripts.fetch_turn_transcript("tok", "turn-1")
    assert out == body
    req = opened.call_args.args[0]
    assert req.full_url == "http://canopy.test/api/harness/turns/turn-1/transcript"
    # urllib sends no Accept-Encoding of its own; we must not add one either.
    assert req.get_header("Accept-encoding") is None


@override_settings(**ENABLED)
def test_a_turn_with_no_transcript_reads_as_empty_not_an_error():
    with _urlopen(b""):
        assert transcripts.fetch_turn_transcript("tok", "turn-1") == b""


@override_settings(**ENABLED)
def test_a_content_encoded_response_is_refused_loudly():
    """canopy streams PLAINTEXT. If anything re-introduces Content-Encoding:
    gzip, urllib hands us raw bytes and, because the blob is multi-member gzip,
    a naive inflate would silently return only the FIRST member — a truncated
    transcript, a wrong cost number, and no error anywhere. Fail instead."""
    with _urlopen(b"\x1f\x8b garbage", headers={"Content-Encoding": "gzip"}):
        with pytest.raises(transcripts.TranscriptEncodingError):
            transcripts.fetch_turn_transcript("tok", "turn-1")


@override_settings(**ENABLED)
def test_an_identity_content_encoding_is_not_treated_as_encoded():
    """`Content-Encoding: identity` is the explicit spelling of "not encoded".
    Refusing it would break a proxy that is doing nothing wrong."""
    with _urlopen(b'{"type":"system"}\n', headers={"Content-Encoding": "identity"}):
        assert transcripts.fetch_turn_transcript("tok", "turn-1") == b'{"type":"system"}\n'


@override_settings(**ENABLED)
def test_a_transfer_encoded_response_is_refused_too():
    """The other spelling of the same bug. `Transfer-Encoding: gzip` carries no
    `Content-Encoding`, so a content-encoding-only check waves it through and
    the raw gzip bytes are handed on as if they were plaintext — every line
    fails to parse and the cost reads ZERO, silently."""
    with _urlopen(b"\x1f\x8b garbage", headers={"Transfer-Encoding": "gzip"}):
        with pytest.raises(transcripts.TranscriptEncodingError):
            transcripts.fetch_turn_transcript("tok", "turn-1")


@override_settings(**ENABLED)
def test_chunked_transfer_encoding_is_not_refused():
    """`chunked` is framing, not compression, and http.client has already
    undone it by the time we read. Refusing it would break the normal case."""
    with _urlopen(b'{"type":"system"}\n', headers={"Transfer-Encoding": "chunked"}):
        assert transcripts.fetch_turn_transcript("tok", "turn-1") == b'{"type":"system"}\n'


@override_settings(**ENABLED)
def test_a_mixed_transfer_encoding_list_is_refused():
    with _urlopen(b"x", headers={"Transfer-Encoding": "gzip, chunked"}):
        with pytest.raises(transcripts.TranscriptEncodingError):
            transcripts.fetch_turn_transcript("tok", "turn-1")


@override_settings(**ENABLED)
def test_a_transcript_over_the_ceiling_raises_rather_than_truncating():
    with _urlopen(b"x" * 64):
        with pytest.raises(transcripts.TranscriptTooLarge, match="turn-1"):
            transcripts.fetch_turn_transcript("tok", "turn-1", max_bytes=16)


@override_settings(**ENABLED, CANOPY_TRANSCRIPT_MAX_BYTES=16)
def test_the_ceiling_defaults_to_the_setting():
    with _urlopen(b"x" * 64):
        with pytest.raises(transcripts.TranscriptTooLarge):
            transcripts.fetch_turn_transcript("tok", "turn-1")


@override_settings(**ENABLED)
def test_canopy_http_errors_surface_as_canopy_errors():
    import urllib.error

    from apps.canopy.client import CanopyError

    err = urllib.error.HTTPError(
        "http://canopy.test", 404, "Not Found", {}, io.BytesIO(b"no such turn")
    )
    with mock.patch("apps.canopy.transcripts.urllib.request.urlopen", side_effect=err):
        with pytest.raises(CanopyError) as caught:
            transcripts.fetch_turn_transcript("tok", "turn-1")
    assert caught.value.status == 404


def test_canopys_truncation_marker_line_survives_the_parser():
    """canopy writes one synthetic line when a turn crosses its 100MB cap. The
    aggregators must skip it, not crash on it."""
    from apps.ingest.parser import parse_session_bytes

    raw = (
        b'{"type":"assistant","uuid":"u1","message":{"model":"m","usage":{"input_tokens":1},'
        b'"content":[{"type":"text","text":"hi"}]}}\n'
        b'{"type":"canopy_transcript_truncated","reason":"exceeded"}\n'
    )
    parsed, events = parse_session_bytes(raw)
    assert parsed.line_count == 2
    assert len(events) >= 1


# ---------------------------------------------------------------------------
# The multi-member gzip trap — over a real socket, because a mocked `urlopen`
# cannot exhibit it.
# ---------------------------------------------------------------------------

# Three separately-compressed batches, exactly as canopy's `append_transcript`
# writes them: each `gzip.compress` call emits a complete gzip MEMBER, and the
# members are concatenated in the stored blob.
#
# The middle member is deliberately padded past `transcripts._CHUNK`, so the
# whole transcript cannot arrive in a single `resp.read(_CHUNK)`. Without that,
# a client that reads ONE chunk and stops still returns the whole body and the
# round-trip test below passes for the wrong reason — verified: with a small
# body, breaking out of the read loop after the first chunk left every test
# green.
_PAD = b"x" * (transcripts._CHUNK + 4096)
MEMBERS = [
    b'{"type":"system","subtype":"init","session_id":"s"}\n',
    b'{"type":"assistant","uuid":"u1","message":{"model":"m","usage":'
    b'{"input_tokens":10,"output_tokens":5},"content":[{"type":"text","text":"' + _PAD + b'"}]}}\n',
    b'{"type":"assistant","uuid":"u2","message":{"model":"m","usage":'
    b'{"input_tokens":20,"output_tokens":7},"content":[{"type":"text","text":"two"}]}}\n',
]
PLAINTEXT = b"".join(MEMBERS)
MULTI_MEMBER_GZIP = b"".join(gzip.compress(m) for m in MEMBERS)

assert len(PLAINTEXT) > transcripts._CHUNK, "the round-trip test needs >1 read to be meaningful"


class _CanopyHandler(BaseHTTPRequestHandler):
    """Two routes: canopy's real one (streamed plaintext) and the falsified
    earlier scheme (raw multi-member gzip + Content-Encoding: gzip)."""

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's contract
        if self.path.endswith("/turns/plaintext/transcript"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            # Chunk it, like a StreamingHttpResponse would. A client that reads
            # one chunk and stops gets a short transcript.
            for start in range(0, len(PLAINTEXT), 8192):
                self.wfile.write(PLAINTEXT[start:start + 8192])
                self.wfile.flush()
        elif self.path.endswith("/turns/gzipped/transcript"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(MULTI_MEMBER_GZIP)))
            self.end_headers()
            self.wfile.write(MULTI_MEMBER_GZIP)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # keep pytest output clean
        return


@pytest.fixture
def canopy_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _CanopyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_fixture_really_is_multi_member(canopy_server):
    """Guard on the guard: if `MULTI_MEMBER_GZIP` were a single member, every
    truncation test below would pass vacuously. A streaming inflate — what an
    HTTP client's content-decoding layer does — stops at the first member."""
    assert zlib.decompressobj(31).decompress(MULTI_MEMBER_GZIP) == MEMBERS[0]
    assert MEMBERS[0] != PLAINTEXT
    assert gzip.decompress(MULTI_MEMBER_GZIP) == PLAINTEXT  # all three, if you read them all


def test_a_multi_member_transcript_round_trips_intact_over_real_http(canopy_server):
    """THE test this client exists for. Every member's content must come back —
    a client that reads one chunk, or inflates only the first gzip member,
    returns a prefix of this and produces a wrong cost number with no symptom."""
    with override_settings(CANOPY_BASE_URL=canopy_server, CANOPY_APP_CREDENTIAL="c"):
        out = transcripts.fetch_turn_transcript("tok", "plaintext")

    assert out == PLAINTEXT
    assert len(out) == len(PLAINTEXT)   # >1 read chunk: a single-read client is short here
    assert out.count(b"\n") == 3
    for member in MEMBERS:
        assert member in out

    # And the bytes are still parseable end to end, so a truncation would show
    # up as a wrong cost rather than an exception — which is exactly why the
    # byte-for-byte assertion above is the one that matters.
    from apps.ingest.cost_aggregator import aggregate
    from apps.ingest.parser import parse_session_bytes

    _parsed, events = parse_session_bytes(out)
    assert aggregate(events)["totals"]["input_tokens"] == 30  # 10 + 20, not 10


def test_httpx_truncates_the_gzip_scheme_our_client_refuses_it(canopy_server):
    """The empirical half. Served with `Content-Encoding: gzip`, a
    content-decoding client (here `httpx`; `curl --compressed` behaves the same)
    returns HTTP 200 and the FIRST MEMBER ONLY — no exception, no warning.
    Our client refuses the response outright instead of handing those truncated
    bytes to the cost aggregator."""
    import httpx

    truncated = httpx.get(f"{canopy_server}/api/harness/turns/gzipped/transcript")
    assert truncated.status_code == 200
    assert truncated.content == MEMBERS[0]      # ← the silent bug, demonstrated
    assert truncated.content != PLAINTEXT

    with override_settings(CANOPY_BASE_URL=canopy_server, CANOPY_APP_CREDENTIAL="c"):
        with pytest.raises(transcripts.TranscriptEncodingError):
            transcripts.fetch_turn_transcript("tok", "gzipped")
