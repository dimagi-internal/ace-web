"""Page-key parsing and Channels group naming for presence.

Pure functions — no Redis, no async — so they unit-test without any
infrastructure. Page keys arrive from the client and are therefore parsed
defensively: anything that is not exactly `<app>:<workspace>:<resource>`,
with each segment matching its charset, is rejected rather than coerced.

Why the charsets are enforced HERE rather than left to the consumer:

* The `app` segment namespaces a shared Redis keyspace. ace-web and
  canopy-web both derive their Redis client from the same `REDIS_URL` on
  shared labs ElastiCache, so an unvalidated `app` lets an ace-web user
  read and write the sibling app's rosters.
* The `workspace` segment is the ONLY thing the membership gate keys on.
  A colon inside a slug would split the key so that a member of `acme`
  lands in `acme:eu`'s roster; `WORKSPACE_RE` forbids the colon outright.
* The global sentinel deliberately leads with `~`, which `WORKSPACE_RE`
  cannot match. Workspace creation enforces no charset, so a slug spelled
  exactly like the sentinel would otherwise bypass the membership gate for
  that tenant. (The consumer ALSO checks that no real workspace shadows
  the sentinel — see apps/presence/consumers.py — because this module
  cannot know what rows exist.)

These values are a cross-app contract: canopy-web's presence keys module
holds the identical constants, and the two must be changed together.
"""
from __future__ import annotations

import hashlib
import re

#: Workspace segment for pages that belong to no workspace (`/settings`,
#: `/system`). The leading `~` is load-bearing: WORKSPACE_RE cannot match
#: it, so no real slug can ever collide with the sentinel.
GLOBAL_SENTINEL = "~global"

WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
APP_RE = re.compile(r"^[a-z0-9-]{1,32}$")

#: Hard cap on a client-supplied page key. Without it the resource segment
#: is unbounded, so a single frame could push an arbitrarily large Redis
#: key name (the `sub_location` field was already capped, the key was not).
MAX_PAGE_KEY_LEN = 512


def parse_page_key(page_key: str) -> tuple[str, str, str] | None:
    """Split `<app>:<workspace>:<resource>` into its three validated parts.

    The resource may itself contain colons (`opp:bednet/run-001`), so the
    split is bounded to 2. Returns None for anything malformed — callers
    MUST treat None as "reject this frame", never as "use a default".
    """
    if not page_key or len(page_key) > MAX_PAGE_KEY_LEN:
        return None
    parts = page_key.split(":", 2)
    if len(parts) != 3:
        return None
    app, workspace, resource = (p.strip() for p in parts)
    if not APP_RE.match(app):
        return None
    if workspace != GLOBAL_SENTINEL and not WORKSPACE_RE.match(workspace):
        return None
    if not resource:
        return None
    return app, workspace, resource


def group_name(page_key: str) -> str:
    """A Channels-legal group name for a page key.

    Channels group names permit only ASCII alphanumerics, hyphens, periods
    and underscores (max 100 chars). Page keys contain ':' and '/', so the
    key is hashed rather than sanitised — sanitising would let two distinct
    keys collide onto one group.
    """
    digest = hashlib.sha1(page_key.encode("utf-8")).hexdigest()[:32]
    return f"presence.{digest}"
