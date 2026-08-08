"""Promote normalized social records into a tracked, public-only corpus."""

from __future__ import annotations

from collections import Counter
import hashlib
from html.entities import html5
from html.parser import HTMLParser
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from . import SCHEMA_VERSION


CORPUS_VERSION = 1
SENTINEL_NAME = ".mistersql-public-corpus"
SENTINEL_TEXT = "Tracked public-only social corpus. Raw archives are forbidden here.\n"
ALLOWED_SOURCES = {"twitter", "mastodon"}
REQUIRED_RECORD_KEYS = {
    "schemaVersion", "socialKind", "source", "persona", "sourceId", "date",
    "contentHtml", "contentText", "metrics",
}
OPTIONAL_RECORD_KEYS = {
    "canonicalUrl", "language", "tags", "contentWarning", "visibility", "poll", "parts",
}
ALLOWED_RECORD_KEYS = REQUIRED_RECORD_KEYS | OPTIONAL_RECORD_KEYS
REQUIRED_PART_KEYS = {"sourceId", "date", "contentHtml", "contentText", "depth", "metrics"}
OPTIONAL_PART_KEYS = {"replyToSourceId", "language", "tags", "contentWarning", "poll"}
ALLOWED_PART_KEYS = REQUIRED_PART_KEYS | OPTIONAL_PART_KEYS


class PublicCorpusError(ValueError):
    """Raised when data is not safe to enter the tracked public corpus."""


class _HTMLAllowlist(HTMLParser):
    ALLOWED_TAGS = {"p", "br", "a", "ul", "ol", "li", "blockquote", "code", "pre", "strong", "em"}
    VOID_TAGS = {"br"}

    def __init__(self) -> None:
        # Validate references ourselves. HTMLParser's eager unescape can throw
        # on legacy numeric references before the validator can reject them.
        super().__init__(convert_charrefs=False)
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.ALLOWED_TAGS:
            raise PublicCorpusError(f"public corpus HTML contains denied tag: {tag}")
        allowed_attrs = {"href", "rel"} if tag == "a" else set()
        if any(name.lower() not in allowed_attrs for name, _ in attrs):
            raise PublicCorpusError(f"public corpus HTML contains denied attribute on {tag}")
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            _require_http_url(href, "HTML link")
        if tag not in self.VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if not self.stack or self.stack.pop() != tag:
            raise PublicCorpusError("public corpus HTML has unbalanced tags")

    def handle_entityref(self, name: str) -> None:
        if name not in html5 and f"{name};" not in html5:
            raise PublicCorpusError("public corpus HTML has an unknown entity reference")

    def handle_charref(self, name: str) -> None:
        try:
            value = int(name[1:], 16) if name.lower().startswith("x") else int(name, 10)
        except ValueError as error:
            raise PublicCorpusError("public corpus HTML has an invalid character reference") from error
        if value < 0 or value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
            raise PublicCorpusError("public corpus HTML has an invalid character reference")

    def finish(self) -> None:
        if self.stack:
            raise PublicCorpusError("public corpus HTML has unclosed tags")


def _require_string(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise PublicCorpusError(f"public corpus has invalid {field}")
    return value


def _require_http_url(value: Any, field: str) -> str:
    value = _require_string(value, field)
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise PublicCorpusError(f"public corpus has invalid {field}") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PublicCorpusError(f"public corpus has non-HTTP {field}")
    return value


def _validate_metrics(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {"likes", "reposts"}:
        raise PublicCorpusError("public corpus has invalid metrics")
    if any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in value.values()):
        raise PublicCorpusError("public corpus has invalid metric count")
    return {"likes": value["likes"], "reposts": value["reposts"]}


def _validate_html(value: Any) -> str:
    value = _require_string(value, "contentHtml")
    parser = _HTMLAllowlist()
    try:
        parser.feed(value)
        parser.close()
        parser.finish()
    except PublicCorpusError:
        raise
    except Exception as error:
        raise PublicCorpusError(
            f"public corpus contains malformed HTML ({type(error).__name__})"
        ) from error
    return value


def _validate_tags(value: Any) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(tag, str) or not tag.strip() for tag in value):
        raise PublicCorpusError("public corpus has invalid tags")
    if value != sorted(set(value), key=lambda tag: (tag.casefold(), tag)):
        raise PublicCorpusError("public corpus tags are not unique and sorted")
    return list(value)


def _validate_poll(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"multiple", "options", "voters", "closed"}:
        raise PublicCorpusError("public corpus has invalid poll")
    if not isinstance(value.get("multiple"), bool):
        raise PublicCorpusError("public corpus poll has invalid multiple flag")
    if not isinstance(value.get("voters"), int) or isinstance(value["voters"], bool) or value["voters"] < 0:
        raise PublicCorpusError("public corpus poll has invalid voter count")
    options = value.get("options")
    if not isinstance(options, list) or not options:
        raise PublicCorpusError("public corpus poll has no options")
    clean_options = []
    for option in options:
        if not isinstance(option, dict) or set(option) != {"name", "votes"}:
            raise PublicCorpusError("public corpus poll has invalid option")
        name = _require_string(option["name"], "poll option name")
        votes = option["votes"]
        if not isinstance(votes, int) or isinstance(votes, bool) or votes < 0:
            raise PublicCorpusError("public corpus poll has invalid option votes")
        clean_options.append({"name": name, "votes": votes})
    result: dict[str, Any] = {
        "multiple": value["multiple"], "options": clean_options, "voters": value["voters"],
    }
    if "closed" in value:
        result["closed"] = _require_string(value["closed"], "poll closed timestamp")
    return result


def _copy_optional(source: dict[str, Any], target: dict[str, Any]) -> None:
    if "canonicalUrl" in source:
        target["canonicalUrl"] = _require_http_url(source["canonicalUrl"], "canonicalUrl")
    if "language" in source:
        target["language"] = _require_string(source["language"], "language")
    if "tags" in source:
        target["tags"] = _validate_tags(source["tags"])
    if "contentWarning" in source:
        target["contentWarning"] = _require_string(source["contentWarning"], "contentWarning")
    if "visibility" in source:
        if source["visibility"] not in {"public", "unlisted"}:
            raise PublicCorpusError("public corpus has denied visibility")
        target["visibility"] = source["visibility"]
    if "poll" in source:
        target["poll"] = _validate_poll(source["poll"])


def _public_part(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - ALLOWED_PART_KEYS or not REQUIRED_PART_KEYS <= set(value):
        raise PublicCorpusError("public corpus has invalid thread part fields")
    depth = value["depth"]
    if not isinstance(depth, int) or isinstance(depth, bool) or depth < 0:
        raise PublicCorpusError("public corpus has invalid thread depth")
    result: dict[str, Any] = {
        "sourceId": _require_string(value["sourceId"], "part sourceId"),
        "date": _require_string(value["date"], "part date"),
        "contentHtml": _validate_html(value["contentHtml"]),
        "contentText": _require_string(value["contentText"], "part contentText"),
        "depth": depth,
        "metrics": _validate_metrics(value["metrics"]),
    }
    if "replyToSourceId" in value:
        result["replyToSourceId"] = _require_string(value["replyToSourceId"], "replyToSourceId")
    _copy_optional(value, result)
    return result


def public_record(value: Any) -> dict[str, Any]:
    """Copy one normalized record through the strict publication allowlist."""
    if not isinstance(value, dict) or set(value) - (ALLOWED_RECORD_KEYS | {"import"}):
        raise PublicCorpusError("normalized record contains unknown publication fields")
    if not REQUIRED_RECORD_KEYS <= set(value):
        raise PublicCorpusError("normalized record lacks required publication fields")
    if value["schemaVersion"] != SCHEMA_VERSION:
        raise PublicCorpusError("normalized record has unsupported schema version")
    if value["source"] not in ALLOWED_SOURCES:
        raise PublicCorpusError("normalized record has unsupported source")
    if value["socialKind"] not in {"post", "storm"}:
        raise PublicCorpusError("normalized record has unsupported social kind")
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "socialKind": value["socialKind"],
        "source": value["source"],
        "persona": _require_string(value["persona"], "persona"),
        "sourceId": _require_string(value["sourceId"], "sourceId"),
        "date": _require_string(value["date"], "date"),
        "contentHtml": _validate_html(value["contentHtml"]),
        "contentText": _require_string(value["contentText"], "contentText"),
        "metrics": _validate_metrics(value["metrics"]),
    }
    _copy_optional(value, result)
    if value["socialKind"] == "storm":
        parts = value.get("parts")
        if not isinstance(parts, list) or len(parts) < 2:
            raise PublicCorpusError("storm has fewer than two parts")
        result["parts"] = [_public_part(part) for part in parts]
    elif "parts" in value:
        raise PublicCorpusError("standalone post unexpectedly contains parts")
    return result


def _record_bytes(record: dict[str, Any]) -> bytes:
    return json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest(records: Iterable[dict[str, Any]], source_digests: dict[str, str]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda item: (item["source"], item["date"], item["sourceId"]))
    digest = hashlib.sha256()
    for record in ordered:
        digest.update(_record_bytes(record))
        digest.update(b"\n")
    by_source = Counter(record["source"] for record in ordered)
    return {
        "corpusVersion": CORPUS_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "records": len(ordered),
        "recordsBySource": dict(sorted(by_source.items())),
        "sourceDatasetSha256": dict(sorted(source_digests.items())),
        "corpusSha256": digest.hexdigest(),
    }


def write_corpus(
    records: Iterable[dict[str, Any]], output: Path, source_digests: dict[str, str]
) -> dict[str, int | str]:
    clean = []
    for record in records:
        try:
            clean.append(public_record(record))
        except PublicCorpusError as error:
            source = record.get("source", "unknown") if isinstance(record, dict) else "unknown"
            source_id = record.get("sourceId", "unknown") if isinstance(record, dict) else "unknown"
            raise PublicCorpusError(f"{source}/{source_id}: {error}") from error
    seen: set[tuple[str, str]] = set()
    shards: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for record in clean:
        identity = (record["source"], record["sourceId"])
        if identity in seen:
            raise PublicCorpusError("public corpus contains a duplicate source identity")
        seen.add(identity)
        year = record["date"][:4]
        if len(year) != 4 or not year.isdigit():
            raise PublicCorpusError("public corpus record has invalid year")
        shards.setdefault((record["source"], year), []).append(record)

    sentinel = output / SENTINEL_NAME
    if output.exists():
        if not output.is_dir() or not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != SENTINEL_TEXT:
            raise PublicCorpusError("public corpus target lacks its safety sentinel")
    else:
        output.mkdir(parents=True)
        sentinel.write_text(SENTINEL_TEXT, encoding="utf-8")

    expected: set[Path] = set()
    changed = 0
    unchanged = 0
    for (source, year), values in sorted(shards.items()):
        values.sort(key=lambda item: (item["date"], item["sourceId"]))
        target = output / "records" / source / f"{year}.json"
        expected.add(target)
        payload = {
            "corpusVersion": CORPUS_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "source": source,
            "year": year,
            "records": values,
        }
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        if target.is_file() and target.read_bytes() == encoded:
            unchanged += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)
            changed += 1

    manifest = build_manifest(clean, source_digests)
    manifest_target = output / "manifest.json"
    expected.add(manifest_target)
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if manifest_target.is_file() and manifest_target.read_bytes() == manifest_bytes:
        unchanged += 1
    else:
        manifest_target.write_bytes(manifest_bytes)
        changed += 1

    removed = 0
    for target in output.glob("records/*/*.json"):
        if target not in expected:
            target.unlink()
            removed += 1
    return {
        "records": len(clean), "shards": len(shards), "changed": changed,
        "unchanged": unchanged, "removed": removed, "corpusSha256": manifest["corpusSha256"],
    }


def load_and_validate(output: Path) -> dict[str, Any]:
    sentinel = output / SENTINEL_NAME
    if not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != SENTINEL_TEXT:
        raise PublicCorpusError("public corpus safety sentinel is missing")
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise PublicCorpusError("public corpus manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise PublicCorpusError("public corpus manifest is invalid JSON") from error
    allowed_manifest = {
        "corpusVersion", "schemaVersion", "records", "recordsBySource",
        "sourceDatasetSha256", "corpusSha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != allowed_manifest:
        raise PublicCorpusError("public corpus manifest has invalid fields")

    records: list[dict[str, Any]] = []
    allowed_files = {sentinel.resolve(), manifest_path.resolve()}
    shard_count = 0
    for target in sorted(output.glob("records/*/*.json")):
        allowed_files.add(target.resolve())
        try:
            shard = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise PublicCorpusError("public corpus shard is invalid JSON") from error
        if not isinstance(shard, dict) or set(shard) != {"corpusVersion", "schemaVersion", "source", "year", "records"}:
            raise PublicCorpusError("public corpus shard has invalid fields")
        if shard["corpusVersion"] != CORPUS_VERSION or shard["schemaVersion"] != SCHEMA_VERSION:
            raise PublicCorpusError("public corpus shard has unsupported version")
        if shard["source"] not in ALLOWED_SOURCES or not isinstance(shard["year"], str):
            raise PublicCorpusError("public corpus shard has invalid identity")
        if not isinstance(shard["records"], list):
            raise PublicCorpusError("public corpus shard records are not a list")
        clean = [public_record(record) for record in shard["records"]]
        if any(record["source"] != shard["source"] or record["date"][:4] != shard["year"] for record in clean):
            raise PublicCorpusError("public corpus record is in the wrong shard")
        if clean != sorted(clean, key=lambda item: (item["date"], item["sourceId"])):
            raise PublicCorpusError("public corpus shard is not deterministically sorted")
        records.extend(clean)
        shard_count += 1

    extras = [path for path in output.rglob("*") if path.is_file() and path.resolve() not in allowed_files]
    if extras:
        raise PublicCorpusError("public corpus contains an unexpected file")
    identities = [(record["source"], record["sourceId"]) for record in records]
    if len(identities) != len(set(identities)):
        raise PublicCorpusError("public corpus contains duplicate source identities")
    rebuilt = build_manifest(records, manifest.get("sourceDatasetSha256", {}))
    if rebuilt != manifest:
        raise PublicCorpusError("public corpus manifest does not match its records")
    return {
        "records": len(records), "shards": shard_count,
        "recordsBySource": manifest["recordsBySource"],
        "corpusSha256": manifest["corpusSha256"],
        "privateValuesEmitted": False,
    }
