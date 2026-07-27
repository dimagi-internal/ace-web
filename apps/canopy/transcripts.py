"""Read a turn's retained raw JSONL back from canopy.

canopy's `GET /api/harness/turns/{id}/transcript` is a StreamingHttpResponse of
INCREMENTALLY-INFLATED PLAINTEXT (`application/x-ndjson`). That wire format is
load-bearing and was arrived at the hard way: canopy stores the blob as
CONCATENATED MULTI-MEMBER gzip, and an earlier attempt to serve it with
`Content-Encoding: gzip` was empirically falsified — both `curl --compressed`
and `httpx` return only the FIRST member, i.e. a 200 with silently truncated
content and no error.

So: `urllib.request` (no Accept-Encoding, no content-decoding, matching
apps/canopy/client.py), a hard refusal if anything ever content-encodes the
response, and a byte ceiling. A short transcript produces a wrong cost number
with no symptom, which is strictly worse than an exception.
"""

from __future__ import annotations

import urllib.error
import urllib.request

from django.conf import settings

from .client import CanopyError

_CHUNK = 256 * 1024


class TranscriptTooLarge(Exception):
    pass


class TranscriptEncodingError(Exception):
    pass


# `chunked` is a framing, not a compression, and `http.client` has already
# undone it by the time we read. Every other transfer-coding is a content
# transformation we would have to reverse — which is precisely the thing this
# module refuses to do.
_SAFE_TRANSFER_CODINGS = {"chunked", "identity"}


def _refuse_if_encoded(resp) -> None:
    """Refuse a response whose body is not the plaintext we asked for.

    Both headers are checked BEFORE the first read. `Content-Encoding` is the
    spelling the falsified canopy scheme used; `Transfer-Encoding` is the other
    spelling of the same bug — nothing in the path emits it and `http.client`
    only implements `chunked`, but a `Transfer-Encoding: gzip` body sails
    through a content-encoding-only check and parses to a cost of ZERO, which
    is the silent-wrong-number failure wearing a different hat.
    """
    content = (resp.getheader("Content-Encoding") or "").strip().lower()
    if content and content != "identity":
        raise TranscriptEncodingError(
            f"canopy transcript came back Content-Encoding: {content!r}; "
            "this route must stream plaintext (a multi-member gzip body "
            "silently truncates to its first member)"
        )
    codings = {
        c.strip().lower()
        for c in (resp.getheader("Transfer-Encoding") or "").split(",")
        if c.strip()
    }
    if codings - _SAFE_TRANSFER_CODINGS:
        raise TranscriptEncodingError(
            f"canopy transcript came back Transfer-Encoding: "
            f"{resp.getheader('Transfer-Encoding')!r}; this route must stream plaintext"
        )


def fetch_turn_transcript(user_token: str, turn_id: str, *, max_bytes: int | None = None) -> bytes:
    """The turn's raw JSONL, byte for byte. Empty bytes when nothing was ever
    appended — absence of a transcript is not absence of a turn."""
    ceiling = max_bytes or settings.CANOPY_TRANSCRIPT_MAX_BYTES
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}/api/harness/turns/{turn_id}/transcript",
        headers={"Authorization": f"Bearer {user_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            _refuse_if_encoded(resp)
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = resp.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > ceiling:
                    raise TranscriptTooLarge(
                        f"turn {turn_id} transcript exceeds {ceiling} bytes"
                    )
                chunks.append(chunk)
            return b"".join(chunks)
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc
