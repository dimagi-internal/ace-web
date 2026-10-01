"""Pure parsing functions for ACE system files.

No Django dependencies — testable in isolation.
"""

from __future__ import annotations

import json
import logging
import re

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?(.*)", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter delimited by ``---`` from a markdown file.

    Returns ``(metadata_dict, body_string)``.  When no frontmatter is found,
    returns ``({}, full_text)``.
    """
    if not text:
        return {}, ""

    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    raw_yaml, body = m.group(1), m.group(2)
    try:
        meta = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        logger.warning("Invalid YAML in frontmatter, treating as no frontmatter")
        return {}, text

    if not isinstance(meta, dict):
        return {}, text

    return meta, body


# ---------------------------------------------------------------------------
# Artifact manifest (TypeScript → Python)
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[str, str] = {
    "build": "app-building",
    "setup": "connect-setup",
    "operate": "llo-management",
    "closeout": "closeout",
}

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL_RE.sub(r"\1_\2", name).lower()


def _normalize_keys(obj: dict) -> dict:
    """Convert camelCase keys to snake_case and normalize phase values."""
    out: dict = {}
    for k, v in obj.items():
        snake = _camel_to_snake(k)
        if snake == "phase" and isinstance(v, str):
            v = _PHASE_MAP.get(v, v)
        out[snake] = v
    return out


def parse_artifact_manifest(ts_source: str) -> list[dict]:
    """Parse the ``ARTIFACT_MANIFEST`` array from a TypeScript source string.

    Steps:
    1. Extract the array body between ``ARTIFACT_MANIFEST...= [`` and ``] as const;``
    2. Normalize TS syntax to JSON (strip comments, quote keys, etc.)
    3. Parse as JSON
    4. Normalize keys to snake_case and phase values to canonical names

    Returns ``[]`` on any parse failure.
    """
    try:
        return _parse_artifact_manifest_inner(ts_source)
    except Exception:
        # A warning, not debug: an unparseable manifest silently empties every
        # consumer (System Overview, the Phases rail's inputs/outputs, file
        # attribution), and that is not a state anyone should find by accident.
        logger.warning("Failed to parse artifact manifest", exc_info=True)
        return []


def _parse_artifact_manifest_inner(ts_source: str) -> list[dict]:
    # 1. Extract the array body. Allow an optional TS type annotation between
    # the identifier and ``=``, e.g. ``ARTIFACT_MANIFEST: readonly Entry[] = [``.
    m = re.search(r"ARTIFACT_MANIFEST\b[^=]*=\s*\[", ts_source)
    if not m:
        return []
    start = m.end()

    # Find the matching `] as const;` (or just `]`)
    end_match = re.search(r"]\s*(?:as\s+const\s*)?;", ts_source[start:])
    if not end_match:
        return []
    array_body = ts_source[start : start + end_match.start()]

    # 2. Normalize TS → JSON
    text = _ts_to_json_array(array_body)

    # 3. Parse
    entries = json.loads(f"[{text}]")

    # 4. Normalize
    return [_normalize_keys(e) for e in entries]


def _ts_to_json_array(text: str) -> str:
    """Best-effort transform of TypeScript object-literal array body to JSON.

    **String literals are lifted out first, and every other rewrite runs on
    what is left.** Each rewrite below is a regex over source text, and a regex
    cannot tell code from the inside of a string. Two of them have broken the
    WHOLE manifest (every entry, not one) by editing string contents:

    * the bare-key quoter matched ``{schema_version: 1`` inside a description
      and inserted a ``"`` mid-string (plugin 0.13.1610, 2026-09-29 — labs
      served an empty manifest, so every step's inputs/outputs, the System
      Overview and manifest-based file attribution went blank);
    * a lone-quote pass paired an apostrophe in a double-quoted description
      with a quote much further down (dimagi-internal/ace-web#732).

    So one left-to-right pass consumes, atomically and in source order, a
    string literal of either style (re-encoded as JSON and parked behind a
    placeholder) or a comment (dropped). A ``//`` inside a string is therefore
    string content, not a comment, and quotes of one style inside a literal of
    the other are just characters. The structural rewrites then only ever see
    code, and the strings go back in last.
    """
    strings: list[str] = []

    def lift(m: re.Match[str]) -> str:
        if m.group("sq") is not None or m.group("dq") is not None:
            strings.append(_ts_string_to_json(m))
            return f"\x00{len(strings) - 1}\x00"
        return ""  # a comment

    text = _TS_TOKEN_RE.sub(lift, text)

    # Add quotes to bare keys: `  skillSlug:` → `  "skillSlug":`
    # Only match keys right after `{` or `,` (object-property syntax).
    text = re.sub(r"([\{,]\s*)(\w+)\s*:", r'\1"\2":', text)

    # Remove trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    # Remove a trailing comma at the very end (before the wrapping `]` we add)
    text = re.sub(r",\s*$", "", text)

    return re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], text)


# One token of TS source that a regex rewrite must not look inside: a string
# literal of either style, or a comment. Alternation order is irrelevant — at
# any position at most one of them can start — what matters is that all four
# are consumed in the SAME pass (see _ts_to_json_array).
_TS_TOKEN_RE = re.compile(
    r"'(?P<sq>(?:\\.|[^'\\])*)'"
    r'|"(?P<dq>(?:\\.|[^"\\])*)"'
    r"|//[^\n]*"
    r"|/\*.*?\*/",
    re.DOTALL,
)


def _ts_string_to_json(m: re.Match[str]) -> str:
    """Re-escape the body of a TS string literal (either quote style) as JSON.

    Resolves TS-source escape sequences first (`\\'` → `'`, `\\"` → `"`),
    then escapes JSON-unsafe chars in the body (`\\`, `"`, control chars).
    """
    inner = m.group("sq") if m.group("sq") is not None else m.group("dq")
    # TS escapes inside the captured body
    inner = inner.replace("\\'", "'").replace('\\"', '"')
    # JSON escapes — order matters; backslash first
    inner = (
        inner.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{inner}"'


# ---------------------------------------------------------------------------
# MCP server tools (TypeScript → Python)
# ---------------------------------------------------------------------------

_TOOL_CALL_RE = re.compile(r"server\.tool\s*\(")
_QUOTED_RE = re.compile(r"\s*(['\"])((?:\\.|(?!\1).)*)\1")


def _read_quoted_string(src: str, start: int) -> tuple[str, int] | None:
    """Read a (possibly concatenated) quoted string starting at ``start``.

    Handles ``'foo'`` and ``"foo" + 'bar'`` (Connect uses + concatenation
    for long .describe() strings). Returns ``(value, end_index)`` or None.
    """
    m = _QUOTED_RE.match(src, start)
    if not m:
        return None
    value = m.group(2).encode("utf-8").decode("unicode_escape")
    end = m.end()
    while True:
        plus = re.match(r"\s*\+\s*", src[end:])
        if not plus:
            break
        next_start = end + plus.end()
        m2 = _QUOTED_RE.match(src, next_start)
        if not m2:
            break
        value += m2.group(2).encode("utf-8").decode("unicode_escape")
        end = m2.end()
    return value, end


def _match_brace_block(src: str, start: int) -> tuple[str, int] | None:
    """Given ``src[start] == '{'``, return the body (without braces) and the
    end index just past the closing ``}``. Naive but skips ``'..'`` / ``".."``
    literals so brace-in-string doesn't break matching.
    """
    if start >= len(src) or src[start] != "{":
        return None
    depth = 0
    i = start
    in_str: str | None = None
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ("'", '"', "`"):
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return src[start + 1 : i], i + 1
        i += 1
    return None


def _extract_param_names(schema_body: str) -> list[str]:
    """Extract top-level keys from a zod schema object body.

    Walks the body tracking brace/paren depth and string state so nested
    objects (``z.object({...})``) and parenthesized .describe() calls don't
    leak inner keys into the top-level list.
    """
    keys: list[str] = []
    i = 0
    n = len(schema_body)
    depth_brace = 0
    depth_paren = 0
    depth_bracket = 0
    in_str: str | None = None
    at_key_position = True  # we just passed `{` or `,` at depth 0
    while i < n:
        c = schema_body[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
            i += 1
            continue
        if c in ("'", '"', "`"):
            in_str = c
            i += 1
            continue
        if c == "/" and i + 1 < n and schema_body[i + 1] == "/":
            nl = schema_body.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == "/" and i + 1 < n and schema_body[i + 1] == "*":
            end = schema_body.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if depth_brace == 0 and depth_paren == 0 and depth_bracket == 0:
            if at_key_position and (c.isalpha() or c == "_"):
                m = re.match(r"[A-Za-z_]\w*", schema_body[i:])
                if m:
                    rest = schema_body[i + m.end() :]
                    if re.match(r"\s*:", rest):
                        keys.append(m.group(0))
                        i += m.end()
                        at_key_position = False
                        continue
            if c == ",":
                at_key_position = True
                i += 1
                continue
            if not c.isspace():
                at_key_position = False
        if c == "{":
            depth_brace += 1
        elif c == "}":
            depth_brace -= 1
        elif c == "(":
            depth_paren += 1
        elif c == ")":
            depth_paren -= 1
        elif c == "[":
            depth_bracket += 1
        elif c == "]":
            depth_bracket -= 1
        i += 1
    return keys


def _preceding_comment(src: str, call_start: int) -> str | None:
    """Walk backwards from ``call_start`` to collect a contiguous block of
    ``// ...`` lines immediately above the call. Returns joined text or None.
    """
    line_start = src.rfind("\n", 0, call_start) + 1
    lines: list[str] = []
    cursor = line_start
    while cursor > 0:
        prev_end = cursor - 1  # the \n
        prev_start = src.rfind("\n", 0, prev_end) + 1
        line = src[prev_start:prev_end].strip()
        if line.startswith("//"):
            text = line.lstrip("/").strip()
            # Skip section dividers like `── Programs ──` or `1. List sheets`
            if text and not re.fullmatch(r"[─=\-_•]+.*?[─=\-_•]+", text):
                lines.append(text)
            cursor = prev_start
        else:
            break
    if not lines:
        return None
    return " ".join(reversed(lines)).strip() or None


def parse_mcp_tools(ts_source: str) -> list[dict]:
    """Parse ``server.tool(...)`` registrations from an MCP server TS file.

    Returns ``[{name, description, params, comment, line}]`` per tool.

    Handles both registration shapes used by the ACE plugin:
    - 3-arg: ``server.tool('name', {schema}, handler)``
    - 4-arg: ``server.tool('name', 'description', {schema}, handler)``

    The 4-arg shape's description is captured verbatim; the 3-arg shape
    falls back to the contiguous ``//`` comment block immediately above
    the call. ``params`` is the list of top-level zod-schema keys.
    """
    tools: list[dict] = []
    for m in _TOOL_CALL_RE.finditer(ts_source):
        call_start = m.start()
        cursor = m.end()
        name_pair = _read_quoted_string(ts_source, cursor)
        if not name_pair:
            continue
        name, cursor = name_pair
        # Skip whitespace + comma
        rest = re.match(r"\s*,\s*", ts_source[cursor:])
        if not rest:
            continue
        cursor += rest.end()

        description: str | None = None
        # 4-arg shape: next token is a quoted string
        next_quoted = _read_quoted_string(ts_source, cursor)
        if next_quoted:
            description, cursor = next_quoted
            rest = re.match(r"\s*,\s*", ts_source[cursor:])
            if rest:
                cursor += rest.end()

        params: list[str] = []
        # Schema can be either an inline `{...}` or a reference to a const
        # (e.g. ``VerificationFlagsZ``). For non-inline references we just
        # surface the identifier as a single param so the UI shows something.
        if cursor < len(ts_source) and ts_source[cursor] == "{":
            block = _match_brace_block(ts_source, cursor)
            if block:
                params = _extract_param_names(block[0])

        comment = _preceding_comment(ts_source, call_start)
        line = ts_source.count("\n", 0, call_start) + 1
        tools.append(
            {
                "name": name,
                "description": description or comment,
                "params": params,
                "line": line,
            }
        )
    return tools


# ---------------------------------------------------------------------------
# QA decisions registry (skills/_qa-decisions.md → {skill: policy})
# ---------------------------------------------------------------------------

#: A registry row: ``| `skill` [note] | **status** | reason |``.
_QA_ROW_RE = re.compile(
    r"^\|\s*`(?P<skill>[^`]+)`[^|]*\|\s*\*\*(?P<status>[^*]+)\*\*\s*\|(?P<reason>.*)\|\s*$"
)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REASON_MAX = 240


def parse_qa_decisions(markdown: str) -> dict[str, dict[str, str]]:
    """The plugin's per-producer QA decisions, from ``skills/_qa-decisions.md``.

    ``{skill: {"status", "label", "reason"}}`` where ``status`` is one of
    ``standalone`` (its own ``<skill>-qa``), ``inline`` (the producer checks
    itself as it works), ``none`` (deliberately no QA — the reason says why),
    ``is_qa`` (the row IS a QA skill), ``pending`` or ``not_applicable``.
    ``label`` is the registry's own wording; ``reason`` its first sentence or
    two, markdown links flattened. Rows that don't parse are skipped — this
    is a display aid, and a malformed row must not take the page down.
    """
    out: dict[str, dict[str, str]] = {}
    for line in markdown.splitlines():
        m = _QA_ROW_RE.match(line.strip())
        if not m:
            continue
        label = m.group("status").strip().strip("`")
        out.setdefault(
            m.group("skill").strip(),
            {"status": _qa_status(label), "label": label, "reason": _qa_reason(m.group("reason"))},
        )
    return out


def _qa_status(label: str) -> str:
    lowered = label.lower()
    if "no qa" in lowered:
        return "none"
    if "inline" in lowered:
        return "inline"
    if "is the qa" in lowered:
        return "is_qa"
    if "has qa" in lowered:
        return "standalone"
    if "not yet migrated" in lowered:
        return "pending"
    return "not_applicable"


def _qa_reason(cell: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", cell).replace("**", "").replace("`", "").strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    reason = ""
    for s in sentences:
        if reason and len(reason) + len(s) + 1 > _REASON_MAX:
            break
        reason = f"{reason} {s}".strip()
    if len(reason) > _REASON_MAX:
        reason = reason[: _REASON_MAX - 1].rstrip() + "…"
    return reason
