#!/usr/bin/env python3
"""Pull webmentions from webmention.io into ``data/webmentions/``.

Runs on a cron in GitHub Actions (``.github/workflows/webmentions.yaml``) —
which is the whole reason it exists as a scheduled job rather than as something
the blog author's browser does. Mentions arrive whether or not anyone is
looking, so collecting them has to happen with nobody looking.

Standard library only, deliberately: a ``requirements.txt`` would drag a
``pip install`` step into a job that makes one GET request.

Design notes, which are most of the content here:

* **Idempotent.** The high-water mark in ``_meta.json`` means the second run
  asks only for what arrived after the first, and ``wm-id`` dedupe catches the
  rest (a mention can be re-sent, and ``since`` is a timestamp filter, not an
  exact cursor). Running twice in a row must write nothing the second time.
* **One file per target page.** Keeps the Hugo lookup trivial and keeps diffs
  readable. A single combined file would rewrite entirely on every pull.
* **Only the fields that render are kept.** Everything else webmention.io
  returns would sit in git history forever for no benefit.
* **No avatar downloading.** Author photos are hotlinked at render time or
  omitted. Committing binaries on a cron is how a repo gets fat.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "webmentions"
META_FILE = DATA_DIR / "_meta.json"

API_URL = "https://webmention.io/api/mentions.jf2"
PER_PAGE = 200
TIMEOUT_SECONDS = 30

# The interaction types worth rendering. `mention-of` is a bare link with no
# stated intent; it is kept because "someone wrote about this" is interesting,
# but the template shows it separately from likes and replies.
KNOWN_PROPERTIES = ("like-of", "repost-of", "in-reply-to", "mention-of")


class PullError(RuntimeError):
    """Anything that should stop the job with a readable message."""


def slug_for_target(target_url: str) -> str:
    """A stable, filesystem-safe filename for one target page.

    Derived from the URL *path*, so a mention of
    ``https://…github.io/mistersql/posts/init/`` lands in
    ``mistersql-posts-init.json``. The site root collapses to ``index``, since
    an empty filename is not usable.

    **This must stay in lockstep with the slug the template computes** — see
    ``layouts/_partials/webmentions.html``, which applies the same
    transformation to Hugo's ``.RelPermalink``. Verified 2026-08-06 that both
    sides agree on a project site (where ``baseURL`` carries a path):
    ``/mistersql/posts/init/`` and the absolute target URL both reduce to
    ``mistersql-posts-init``. If either side's rule changes, mentions stop
    rendering and nothing errors — the lookup just misses.
    """
    path = urllib.parse.urlparse(target_url).path
    trimmed = path.strip("/")
    if not trimmed:
        return "index"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", trimmed).strip("-").lower()
    return slug or "index"


def trim_mention(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Keep only what the templates render; drop anything unrecognised.

    Returns ``None`` for entries that cannot be rendered — a mention with no
    id, no target or an unknown property is not worth a line in the repo.
    """
    wm_id = raw.get("wm-id")
    prop = raw.get("wm-property")
    target = raw.get("wm-target")
    if wm_id is None or prop not in KNOWN_PROPERTIES or not target:
        return None

    author = raw.get("author") or {}
    trimmed: dict[str, Any] = {
        "wm-id": wm_id,
        "wm-property": prop,
        "wm-target": target,
        "url": raw.get("url") or "",
        "published": raw.get("published") or raw.get("wm-received") or "",
        "author": {
            "name": (author.get("name") or "").strip(),
            "photo": author.get("photo") or "",
            "url": author.get("url") or "",
        },
    }

    # Replies carry text. Deliberately the plain-text form, never `content.html`:
    # this is untrusted input from strangers, and the first person to send a
    # reply containing a <script> tag should not be interesting. See the
    # template, which also does not mark it safe.
    if prop == "in-reply-to":
        content = raw.get("content") or {}
        text = (content.get("text") or "").strip()
        if text:
            trimmed["content"] = text

    return trimmed


def fetch_mentions(token: str, since: str | None) -> list[dict[str, Any]]:
    """One page of mentions from webmention.io, newest first."""
    params = {"token": token, "per-page": str(PER_PAGE)}
    if since:
        params["since"] = since
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"

    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code == 401:
            raise PullError(
                "webmention.io rejected the token. Check the WEBMENTION_IO_TOKEN secret."
            ) from error
        raise PullError(f"webmention.io returned HTTP {error.code}.") from error
    except urllib.error.URLError as error:
        raise PullError(f"Could not reach webmention.io: {error.reason}") from error

    children = body.get("children")
    if not isinstance(children, list):
        raise PullError("webmention.io returned no 'children' array.")
    return children


def read_token() -> str:
    """The webmention.io API key, from the environment or a local ``.env``.

    Two names are accepted: ``WEBMENTIONS_API_KEY`` is what the repo's ``.env``
    uses, and ``WEBMENTION_IO_TOKEN`` is kept working so an existing Actions
    secret under that name does not silently stop the job.

    The ``.env`` fallback exists only so the script can be run by hand while
    setting things up; in Actions the value arrives as an environment variable
    and ``.env`` is not committed.
    """
    for name in ("WEBMENTIONS_API_KEY", "WEBMENTION_IO_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value

    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return ""
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() in ("WEBMENTIONS_API_KEY", "WEBMENTION_IO_TOKEN"):
                return value.strip().strip("\"'")
    except OSError:
        return ""
    return ""


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt file must not wedge the job forever: treat it as empty and
        # let this run rewrite it.
        return fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys so an unchanged set of mentions serialises identically and
    # produces no diff — which is what lets the workflow skip empty commits.
    text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def merge_into_files(mentions: list[dict[str, Any]]) -> tuple[dict[Path, Any], int]:
    """Group new mentions by target page and merge with what is on disk.

    Returns the files to write and how many mentions were genuinely new.
    Existing entries win on ``wm-id`` collision, so a re-sent mention does not
    churn the file.
    """
    by_slug: dict[str, list[dict[str, Any]]] = {}
    for mention in mentions:
        trimmed = trim_mention(mention)
        if trimmed is None:
            continue
        by_slug.setdefault(slug_for_target(trimmed["wm-target"]), []).append(trimmed)

    writes: dict[Path, Any] = {}
    added = 0
    for slug, incoming in by_slug.items():
        path = DATA_DIR / f"{slug}.json"
        existing = load_json(path, [])
        if not isinstance(existing, list):
            existing = []
        seen = {entry.get("wm-id") for entry in existing}

        merged = list(existing)
        for entry in incoming:
            if entry["wm-id"] in seen:
                continue
            seen.add(entry["wm-id"])
            merged.append(entry)
            added += 1

        if len(merged) != len(existing):
            # Oldest first: a page's mentions read as a conversation, and stable
            # ordering keeps diffs to appended lines.
            merged.sort(key=lambda entry: (entry.get("published") or "", entry["wm-id"]))
            writes[path] = merged

    return writes, added


def newest_timestamp(mentions: list[dict[str, Any]]) -> str | None:
    """The high-water mark to ask from next time."""
    stamps = [
        raw.get("wm-received") or raw.get("published")
        for raw in mentions
        if raw.get("wm-received") or raw.get("published")
    ]
    return max(stamps) if stamps else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching the repo.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Read a saved API response instead of calling webmention.io. "
        "Lets the script be exercised locally with no token.",
    )
    args = parser.parse_args(argv)

    meta = load_json(META_FILE, {})
    since = meta.get("since") if isinstance(meta, dict) else None

    try:
        if args.fixture:
            body = json.loads(args.fixture.read_text(encoding="utf-8"))
            mentions = body.get("children", [])
        else:
            token = read_token()
            if not token:
                raise PullError(
                    "No webmention.io token. Set WEBMENTIONS_API_KEY "
                    "(as a repository secret in Actions, or in .env locally)."
                )
            mentions = fetch_mentions(token, since)
    except PullError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if not mentions:
        print("No new mentions.")
        return 0

    writes, added = merge_into_files(mentions)
    high_water = newest_timestamp(mentions)

    if not writes:
        # Everything returned was already on disk. Common on a re-run, and the
        # reason the workflow checks `git status` before committing.
        print(f"Fetched {len(mentions)} mention(s); nothing new.")
        return 0

    if args.dry_run:
        print(f"Would add {added} mention(s) across {len(writes)} file(s):")
        for path in sorted(writes):
            print(f"  {path.relative_to(REPO_ROOT)} -> {len(writes[path])} total")
        if high_water:
            print(f"  would set since = {high_water}")
        return 0

    for path, value in writes.items():
        write_json(path, value)
    if high_water:
        write_json(META_FILE, {"since": high_water})

    print(f"Added {added} mention(s) across {len(writes)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
