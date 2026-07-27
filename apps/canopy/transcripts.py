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
            encoding = (resp.getheader("Content-Encoding") or "").strip().lower()
            if encoding and encoding != "identity":
                raise TranscriptEncodingError(
                    f"canopy transcript came back Content-Encoding: {encoding!r}; "
                    "this route must stream plaintext (a multi-member gzip body "
                    "silently truncates to its first member)"
                )
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
