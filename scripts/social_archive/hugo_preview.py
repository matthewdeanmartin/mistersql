"""Compile canonical records into quarantined Hugo draft pages."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

SENTINEL_NAME = ".mistersql-private-preview"
SENTINEL_TEXT = "Generated private preview. Do not commit or publish.\n"


class PreviewCompileError(ValueError):
    """Raised when the quarantined preview boundary is invalid."""


@dataclass(frozen=True)
class CompileReport:
    pages: int
    changed: int
    unchanged: int
    removed: int

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "pages": self.pages,
            "changed": self.changed,
            "unchanged": self.unchanged,
            "removed": self.removed,
            "drafts": True,
            "publishable": False,
        }


def _title(text: str) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= 96:
        return compact
    return compact[:93].rstrip() + "…"


def _page(item: dict[str, Any]) -> str:
    front_matter: dict[str, Any] = {
        "title": _title(item["contentText"]),
        "date": item["date"],
        "draft": True,
        "hideTitle": True,
        "privatePreview": True,
        "socialKind": item["socialKind"],
        "source": item["source"],
        "persona": item["persona"],
        "sourceId": item["sourceId"],
        "socialMetrics": item.get("metrics", {"likes": 0, "reposts": 0}),
        "canonicalUrl": item.get("canonicalUrl"),
        "url": f"/posts/{item['source']}/{item['sourceId']}/",
    }
    if item.get("language"):
        front_matter["language"] = item["language"]
    if item.get("tags"):
        front_matter["tags"] = item["tags"]
    if item.get("parts"):
        front_matter["socialParts"] = item["parts"]
    if item.get("contentWarning"):
        front_matter["contentWarning"] = item["contentWarning"]
    if item.get("poll"):
        front_matter["socialPoll"] = item["poll"]
    clean_front_matter = {key: value for key, value in front_matter.items() if value is not None}
    return json.dumps(clean_front_matter, ensure_ascii=False, indent=2, sort_keys=True) + "\n" + item["contentHtml"] + "\n"


def compile_preview(result: Any, output: Path, *, source: str | None = None) -> CompileReport:
    sentinel = output / SENTINEL_NAME
    if output.exists():
        if not output.is_dir() or not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != SENTINEL_TEXT:
            raise PreviewCompileError("preview target exists without the expected safety sentinel")
    else:
        output.mkdir(parents=True)
        sentinel.write_text(SENTINEL_TEXT, encoding="utf-8")

    sources = {item.get("source") for item in result.objects}
    if None in sources or len(sources) > 1:
        raise PreviewCompileError("preview batch must contain exactly one source")
    batch_source = source or (next(iter(sources)) if sources else None)
    if batch_source not in {"twitter", "mastodon"} or (sources and sources != {batch_source}):
        raise PreviewCompileError("preview source is missing or inconsistent")

    expected: set[Path] = set()
    changed = 0
    unchanged = 0
    for item in result.objects:
        year = item["date"][:4]
        target = output / year / f"{batch_source}-{item['sourceId']}.html"
        expected.add(target)
        rendered = _page(item)
        encoded = rendered.encode("utf-8")
        # Compare bytes. Text-mode reads normalize a few legacy newline forms,
        # which made records containing those characters look changed forever.
        if target.is_file() and target.read_bytes() == encoded:
            unchanged += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        changed += 1

    removed = 0
    for target in output.glob(f"*/{batch_source}-*.html"):
        if target not in expected:
            target.unlink()
            removed += 1
    for directory in sorted((path for path in output.iterdir() if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return CompileReport(len(expected), changed, unchanged, removed)
