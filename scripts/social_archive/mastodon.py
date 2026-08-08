"""Fail-closed Mastodon ActivityPub archive normalization."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit
import zipfile

from . import SCHEMA_VERSION


OUTBOX_MEMBER_NAME = "outbox.json"
PUBLIC_AUDIENCE = "https://www.w3.org/ns/activitystreams#Public"

ACTIVITY_KEYS = {"actor", "cc", "id", "object", "published", "to", "type"}
OBJECT_KEYS = {
    "_misskey_quote", "anyOf", "atomUri", "attachment", "attributedTo", "cc",
    "closed", "content", "contentMap", "context", "conversation", "endTime",
    "id", "inReplyTo", "inReplyToAtomUri", "interactionPolicy", "likes",
    "oneOf", "published", "quote", "quoteAuthorization", "quoteUri", "replies",
    "sensitive", "shares", "summary", "tag", "to", "type", "updated", "url",
    "votersCount",
}
TAG_KEYS = {
    "attributedTo", "discoverable", "href", "id", "name", "published",
    "sensitive", "summary", "totalItems", "type", "updated", "url",
}
ATTACHMENT_KEYS = {
    "blurhash", "duration", "focalPoint", "height", "href", "mediaType",
    "name", "type", "url", "width",
}
POLL_OPTION_KEYS = {"name", "replies", "type"}
SOURCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class MastodonImportError(ValueError):
    """Raised when an export cannot be normalized without guessing."""


@dataclass(frozen=True)
class MastodonNode:
    source_id: str
    aliases: tuple[str, ...]
    created_at: datetime
    canonical_url: str
    content_html: str
    content_text: str
    language: str | None
    parent_ref: str | None
    tags: tuple[str, ...]
    content_warning: str | None
    visibility: str
    likes: int
    reposts: int
    poll: dict[str, Any] | None
    attachments_ignored: int


@dataclass(frozen=True)
class MastodonImportResult:
    objects: tuple[dict[str, Any], ...]
    exclusions: dict[str, tuple[str, ...]]
    source_sha256: str
    attachments_ignored: int

    def report(self) -> dict[str, Any]:
        kinds = Counter(item["socialKind"] for item in self.objects)
        included_records = sum(len(item.get("parts", [item])) for item in self.objects)
        reasons = Counter(reason for values in self.exclusions.values() for reason in values)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "objects": len(self.objects),
            "includedRecords": included_records,
            "objectKinds": dict(sorted(kinds.items())),
            "excluded": len(self.exclusions),
            "exclusionReasons": dict(sorted(reasons.items())),
            "contentWarnings": sum(bool(item.get("contentWarning")) for item in self.objects),
            "polls": sum(bool(item.get("poll")) for item in self.objects),
            "attachmentsIgnored": self.attachments_ignored,
            "sourceSha256": self.source_sha256,
            "privateValuesEmitted": False,
        }


def _outbox_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    matches = [
        item for item in archive.infolist()
        if not item.is_dir() and PurePosixPath(item.filename).name == OUTBOX_MEMBER_NAME
    ]
    if len(matches) != 1:
        raise MastodonImportError(f"expected exactly one Mastodon outbox dataset; found {len(matches)}")
    return matches[0]


def read_outbox(path: Path) -> tuple[dict[str, Any], str]:
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        member = _outbox_member(archive)
        chunks: list[bytes] = []
        with archive.open(member) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                chunks.append(chunk)
    try:
        value = json.loads(b"".join(chunks).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MastodonImportError("Mastodon outbox is not valid UTF-8 JSON") from error
    if (
        not isinstance(value, dict)
        or value.get("type") != "OrderedCollection"
        or not isinstance(value.get("orderedItems"), list)
    ):
        raise MastodonImportError("Mastodon outbox is not an OrderedCollection")
    return value, digest.hexdigest()


def schema_summary(path: Path) -> dict[str, Any]:
    outbox, digest = read_outbox(path)
    activity_keys: set[str] = set()
    object_keys: set[str] = set()
    activity_types: Counter[str] = Counter()
    object_types: Counter[str] = Counter()
    malformed = 0
    for activity in outbox["orderedItems"]:
        if not isinstance(activity, dict):
            malformed += 1
            continue
        activity_keys.update(str(key) for key in activity)
        activity_types[str(activity.get("type", "[missing]"))] += 1
        obj = activity.get("object")
        if isinstance(obj, dict):
            object_keys.update(str(key) for key in obj)
            object_types[str(obj.get("type", "[missing]"))] += 1
    return {
        "records": len(outbox["orderedItems"]),
        "malformedRecords": malformed,
        "activityTypes": dict(sorted(activity_types.items())),
        "objectTypes": dict(sorted(object_types.items())),
        "activityKeys": sorted(activity_keys),
        "objectKeys": sorted(object_keys),
        "unknownActivityKeys": sorted(activity_keys - ACTIVITY_KEYS),
        "unknownObjectKeys": sorted(object_keys - OBJECT_KEYS),
        "outboxDatasetSha256": digest,
        "contentValuesEmitted": False,
    }


def _sequence(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    if value is None:
        return []
    raise MastodonImportError("audience field is not a string or string list")


def _public_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _count(value: Any, field: str) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise MastodonImportError(f"Mastodon object has an invalid {field}")


def _collection_count(value: Any, field: str) -> int:
    if value is None:
        return 0
    if not isinstance(value, dict) or set(value) - {"id", "totalItems", "type"}:
        raise MastodonImportError(f"Mastodon object has an invalid {field} collection")
    return _count(value.get("totalItems"), f"{field}.totalItems")


class _Sanitizer(HTMLParser):
    ALLOWED = {"p", "br", "a", "ul", "ol", "li", "blockquote", "code", "pre", "strong", "em"}
    VOID = {"br"}
    BLOCKED = {"script", "style", "iframe", "object", "embed", "svg", "math"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.text: list[str] = []
        self.stack: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED:
            self.blocked_depth += 1
            return
        if self.blocked_depth or tag not in self.ALLOWED:
            return
        if tag == "a":
            href = next((value for key, value in attrs if key.lower() == "href"), None)
            safe = _public_url(href)
            if safe:
                self.output.append(f'<a href="{html.escape(safe, quote=True)}" rel="nofollow noopener">')
                self.stack.append(tag)
            return
        self.output.append(f"<{tag}>")
        if tag not in self.VOID:
            self.stack.append(tag)
        if tag == "br":
            self.text.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.BLOCKED:
            if self.blocked_depth:
                self.blocked_depth -= 1
            return
        if self.blocked_depth or tag not in self.ALLOWED or tag in self.VOID:
            return
        if tag in self.stack:
            while self.stack:
                opened = self.stack.pop()
                self.output.append(f"</{opened}>")
                if opened == tag:
                    break
            if tag in {"p", "li", "blockquote", "pre"}:
                self.text.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.output.append(html.escape(data))
            self.text.append(data)

    def finish(self) -> tuple[str, str]:
        while self.stack:
            self.output.append(f"</{self.stack.pop()}>")
        clean_html = "".join(self.output).strip()
        clean_text = re.sub(r"[ \t]+", " ", "".join(self.text))
        clean_text = re.sub(r"\n{3,}", "\n\n", clean_text).strip()
        return clean_html, clean_text


def _sanitize(raw: Any) -> tuple[str, str]:
    if not isinstance(raw, str):
        raise MastodonImportError("Mastodon object has invalid content")
    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return parser.finish()


def _source_id(object_id: str) -> str:
    path = urlsplit(object_id).path.rstrip("/")
    value = PurePosixPath(path).name
    if not value or not SOURCE_ID_PATTERN.fullmatch(value):
        raise MastodonImportError("Mastodon object has no safe stable source ID")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise MastodonImportError("Mastodon object has no publication timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise MastodonImportError("Mastodon object has an invalid publication timestamp") from error
    if result.tzinfo is None:
        raise MastodonImportError("Mastodon publication timestamp lacks a timezone")
    return result


def _opaque_id(source_id: str) -> str:
    return hashlib.sha256(f"mastodon:{source_id}".encode()).hexdigest()[:16]


def _reason(exclusions: dict[str, list[str]], source_id: str, reason: str) -> None:
    exclusions.setdefault(_opaque_id(source_id), []).append(reason)


def _poll(obj: dict[str, Any]) -> dict[str, Any] | None:
    field = "anyOf" if isinstance(obj.get("anyOf"), list) else "oneOf" if isinstance(obj.get("oneOf"), list) else None
    if field is None:
        return None
    options: list[dict[str, Any]] = []
    for option in obj[field]:
        if not isinstance(option, dict) or set(option) - POLL_OPTION_KEYS or option.get("type") != "Note":
            raise MastodonImportError("Mastodon poll has an invalid option")
        name = option.get("name")
        if not isinstance(name, str) or not name.strip():
            raise MastodonImportError("Mastodon poll option has no name")
        options.append({
            "name": html.unescape(name).strip(),
            "votes": _collection_count(option.get("replies"), "poll replies"),
        })
    result: dict[str, Any] = {
        "multiple": field == "anyOf",
        "options": options,
        "voters": _count(obj.get("votersCount"), "votersCount"),
    }
    if isinstance(obj.get("closed"), str):
        result["closed"] = obj["closed"]
    return result


def _parse_create(
    activity: dict[str, Any], exclusions: dict[str, list[str]], actor: str
) -> MastodonNode | None:
    if set(activity) - ACTIVITY_KEYS:
        raise MastodonImportError("unrecognized Mastodon activity fields")
    obj = activity.get("object")
    if not isinstance(obj, dict) or obj.get("type") not in {"Note", "Question"}:
        raise MastodonImportError("Mastodon Create does not contain a supported object")
    if set(obj) - OBJECT_KEYS:
        raise MastodonImportError("unrecognized Mastodon object fields")
    if activity.get("actor") != actor or obj.get("attributedTo") != actor:
        raise MastodonImportError("Mastodon outbox contains mixed authorship")

    object_id = _public_url(obj.get("id"))
    if object_id is None:
        raise MastodonImportError("Mastodon object has no public HTTP ID")
    source_id = _source_id(object_id)
    audiences_to = set(_sequence(activity.get("to")) + _sequence(obj.get("to")))
    audiences_cc = set(_sequence(activity.get("cc")) + _sequence(obj.get("cc")))
    if PUBLIC_AUDIENCE not in audiences_to and PUBLIC_AUDIENCE not in audiences_cc:
        _reason(exclusions, source_id, "nonpublic_visibility")
        return None
    visibility = "public" if PUBLIC_AUDIENCE in audiences_to else "unlisted"

    clean_html, clean_text = _sanitize(obj.get("content"))
    if not clean_text:
        _reason(exclusions, source_id, "empty_content")
        return None
    canonical = _public_url(obj.get("url")) or object_id
    parent = obj.get("inReplyTo")
    if parent is not None and _public_url(parent) is None:
        raise MastodonImportError("Mastodon reply has an invalid parent URL")

    raw_tags = obj.get("tag", [])
    if not isinstance(raw_tags, list):
        raise MastodonImportError("Mastodon object has invalid tags")
    tags: set[str] = set()
    for tag in raw_tags:
        if not isinstance(tag, dict) or set(tag) - TAG_KEYS:
            raise MastodonImportError("Mastodon object has an invalid tag")
        if tag.get("type") == "Hashtag":
            name = tag.get("name")
            if not isinstance(name, str):
                raise MastodonImportError("Mastodon hashtag has no name")
            name = html.unescape(name).strip().lstrip("#")
            if name:
                tags.add(name)

    attachments = obj.get("attachment", [])
    if not isinstance(attachments, list):
        raise MastodonImportError("Mastodon object has invalid attachments")
    for attachment in attachments:
        if not isinstance(attachment, dict) or set(attachment) - ATTACHMENT_KEYS:
            raise MastodonImportError("Mastodon object has an invalid attachment")

    content_map = obj.get("contentMap")
    language = None
    if content_map is not None:
        if not isinstance(content_map, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in content_map.items()):
            raise MastodonImportError("Mastodon object has an invalid contentMap")
        if len(content_map) == 1:
            language = next(iter(content_map))

    warning = obj.get("summary")
    if warning is not None and not isinstance(warning, str):
        raise MastodonImportError("Mastodon object has an invalid content warning")
    warning = html.unescape(warning).strip() if warning else None
    aliases = tuple(sorted({object_id, canonical}))
    return MastodonNode(
        source_id=source_id,
        aliases=aliases,
        created_at=_timestamp(obj.get("published") or activity.get("published")),
        canonical_url=canonical,
        content_html=clean_html,
        content_text=clean_text,
        language=language,
        parent_ref=parent,
        tags=tuple(sorted(tags, key=lambda value: (value.casefold(), value))),
        content_warning=warning,
        visibility=visibility,
        likes=_collection_count(obj.get("likes"), "likes"),
        reposts=_collection_count(obj.get("shares"), "shares"),
        poll=_poll(obj) if obj.get("type") == "Question" else None,
        attachments_ignored=len(attachments),
    )


def _part(node: MastodonNode, depth: int, parent_id: str | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sourceId": node.source_id,
        "date": node.created_at.isoformat(),
        "contentText": node.content_text,
        "contentHtml": node.content_html,
        "depth": depth,
        "metrics": {"likes": node.likes, "reposts": node.reposts},
    }
    if parent_id:
        result["replyToSourceId"] = parent_id
    for key, value in (
        ("language", node.language), ("tags", list(node.tags) if node.tags else None),
        ("contentWarning", node.content_warning), ("poll", node.poll),
    ):
        if value is not None:
            result[key] = value
    return result


def _canonical(
    nodes: list[MastodonNode], parent_ids: dict[str, str | None], persona: str, digest: str
) -> dict[str, Any]:
    root = nodes[0]
    kind = "storm" if len(nodes) > 1 else "post"
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "socialKind": kind,
        "source": "mastodon",
        "persona": persona,
        "sourceId": root.source_id,
        "date": root.created_at.isoformat(),
        "canonicalUrl": root.canonical_url,
        "contentText": root.content_text,
        "contentHtml": root.content_html,
        "visibility": root.visibility,
        "metrics": {"likes": root.likes, "reposts": root.reposts},
        "import": {"adapter": "mastodon-v1", "outboxDatasetSha256": digest},
    }
    for key, value in (
        ("language", root.language), ("contentWarning", root.content_warning), ("poll", root.poll),
    ):
        if value is not None:
            result[key] = value
    tags = sorted(
        {tag for node in nodes for tag in node.tags},
        key=lambda value: (value.casefold(), value),
    )
    if tags:
        result["tags"] = tags
    if kind == "storm":
        depths = {root.source_id: 0}
        parts = []
        for node in nodes:
            parent_id = parent_ids[node.source_id]
            if parent_id:
                if parent_id not in depths:
                    raise MastodonImportError("Mastodon thread is not parent-before-child")
                depths[node.source_id] = depths[parent_id] + 1
            parts.append(_part(node, depths[node.source_id], parent_id))
        result["parts"] = parts
    return result


def normalize(path: Path, *, persona: str, owner_controlled: bool) -> MastodonImportResult:
    if not owner_controlled:
        raise MastodonImportError("--owner-controlled is required for a Mastodon archive")
    persona = persona.strip()
    if not persona:
        raise MastodonImportError("persona is required")
    outbox, digest = read_outbox(path)
    exclusions: dict[str, list[str]] = {}
    items = outbox["orderedItems"]
    create_actors = {
        item.get("actor") for item in items
        if isinstance(item, dict) and item.get("type") == "Create" and isinstance(item.get("actor"), str)
    }
    if len(create_actors) != 1:
        raise MastodonImportError("Mastodon outbox does not have exactly one author")
    actor = next(iter(create_actors))

    nodes: dict[str, MastodonNode] = {}
    aliases: dict[str, str] = {}
    attachments_ignored = 0
    for activity in items:
        if not isinstance(activity, dict):
            raise MastodonImportError("Mastodon outbox contains a non-object activity")
        activity_type = activity.get("type")
        if activity_type == "Announce":
            activity_id = str(activity.get("id", "invalid-announce"))
            _reason(exclusions, activity_id, "boost")
            continue
        if activity_type != "Create":
            raise MastodonImportError("Mastodon outbox contains an unsupported activity type")
        node = _parse_create(activity, exclusions, actor)
        if node is None:
            continue
        if node.source_id in nodes or any(alias in aliases for alias in node.aliases):
            _reason(exclusions, node.source_id, "duplicate")
            continue
        nodes[node.source_id] = node
        for alias in node.aliases:
            aliases[alias] = node.source_id
        attachments_ignored += node.attachments_ignored

    parent_ids = {
        source_id: aliases.get(node.parent_ref) if node.parent_ref else None
        for source_id, node in nodes.items()
    }
    validity: dict[str, bool] = {}
    visiting: set[str] = set()

    def valid(source_id: str) -> bool:
        if source_id in validity:
            return validity[source_id]
        node = nodes[source_id]
        if source_id in visiting:
            _reason(exclusions, source_id, "reply_cycle")
            validity[source_id] = False
            return False
        if node.parent_ref is None:
            validity[source_id] = True
            return True
        parent_id = parent_ids[source_id]
        if parent_id is None:
            _reason(exclusions, source_id, "external_context")
            validity[source_id] = False
            return False
        visiting.add(source_id)
        parent_valid = valid(parent_id)
        visiting.discard(source_id)
        if not parent_valid:
            _reason(exclusions, source_id, "excluded_ancestor")
        validity[source_id] = parent_valid
        return parent_valid

    valid_nodes = {source_id: node for source_id, node in nodes.items() if valid(source_id)}
    children: dict[str, list[MastodonNode]] = defaultdict(list)
    roots: list[MastodonNode] = []
    for source_id, node in valid_nodes.items():
        parent_id = parent_ids[source_id]
        if parent_id and parent_id in valid_nodes:
            children[parent_id].append(node)
        else:
            roots.append(node)
    for values in children.values():
        values.sort(key=lambda item: (item.created_at, item.source_id))
    roots.sort(key=lambda item: (item.created_at, item.source_id))

    objects: list[dict[str, Any]] = []
    for root in roots:
        collected: list[MastodonNode] = []
        stack = [root]
        while stack:
            current = stack.pop()
            collected.append(current)
            stack.extend(reversed(children.get(current.source_id, [])))
        objects.append(_canonical(collected, parent_ids, persona, digest))
    objects.sort(key=lambda item: (item["date"], item["sourceId"]))
    frozen = {key: tuple(sorted(set(values))) for key, values in sorted(exclusions.items())}
    return MastodonImportResult(tuple(objects), frozen, digest, attachments_ignored)


def write_staging(result: MastodonImportResult, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    records = output / "records"
    records.mkdir()
    for item in result.objects:
        target = records / f"mastodon-{item['persona']}-{item['sourceId']}.json"
        target.write_text(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "report.json").write_text(json.dumps(result.report(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "exclusions.json").write_text(json.dumps(result.exclusions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
