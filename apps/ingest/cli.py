"""ace-upload: Upload .jsonl Claude CLI sessions to ace-web.

This is a standalone script. It does NOT import Django. It uses httpx to
POST files to the ingest endpoint and reads config from ~/.ace/config.toml.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

import httpx


@dataclass
class Config:
    server: str
    token: str


def load_config(path: Path) -> Config:
    if not path.exists():
        print(f"Config not found: {path}", file=sys.stderr)
        print("Run: ace-upload --configure", file=sys.stderr)
        sys.exit(1)
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(server=data["server"], token=data["token"])


def upload_file(path: Path, config: Config) -> bool:
    url = f"{config.server.rstrip('/')}/api/ingest/upload"
    with open(path, "rb") as f:
        resp = httpx.post(
            url,
            files={"file": (path.name, f, "application/x-ndjson")},
            headers={"Authorization": f"Bearer {config.token}"},
            timeout=60,
        )
    if resp.status_code == 201:
        data = resp.json().get("data", {})
        slug = data.get("session_slug")
        count = data.get("message_count", "?")
        print(f"  ok {path.name} -> {slug} ({count} messages)", file=sys.stderr)
        return True
    if resp.status_code == 409:
        print(f"  -- {path.name} (already uploaded, skipping)", file=sys.stderr)
        return False
    error = resp.json().get("error", {}).get("message", resp.text[:200])
    print(f"  FAIL {path.name}: {resp.status_code} {error}", file=sys.stderr)
    return False


def configure(config_path: Path) -> None:
    print("ace-upload configuration")
    server = input("Server URL [https://labs.connect.dimagi.com/ace]: ").strip()
    if not server:
        server = "https://labs.connect.dimagi.com/ace"
    token = input("Personal token: ").strip()
    if not token:
        print("Token is required.", file=sys.stderr)
        sys.exit(1)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f'server = "{server}"\ntoken = "{token}"\n')
    print(f"Config written to {config_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ace-upload",
        description="Upload .jsonl Claude CLI sessions to ace-web.",
    )
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="A .jsonl file or directory of .jsonl files",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Set up server URL and token",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path.home() / ".ace" / "config.toml",
        help="Config file path",
    )
    args = parser.parse_args()

    if args.configure:
        configure(args.config)
        return

    if not args.path:
        parser.error("Provide a .jsonl file or directory, or use --configure")

    config = load_config(args.config)
    target = args.path

    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*.jsonl"))
        if not files:
            print(f"No .jsonl files found in {target}", file=sys.stderr)
            sys.exit(1)
        print(f"Found {len(files)} .jsonl files", file=sys.stderr)
    else:
        print(f"Not found: {target}", file=sys.stderr)
        sys.exit(1)

    successes = 0
    for f in files:
        if upload_file(f, config):
            successes += 1

    print(f"\n{successes}/{len(files)} uploaded", file=sys.stderr)
    sys.exit(0 if successes == len(files) else 1)


if __name__ == "__main__":
    main()
