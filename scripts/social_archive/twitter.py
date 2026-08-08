"""Fail-closed Twitter archive normalization and thread classification."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit
import zipfile

from . import SCHEMA_VERSION


TWEET_MEMBER_NAME = "tweets.js"
JS_ASSIGNMENT_MARKER = "="
TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"

# Keys are either consumed or explicitly discarded. An unrecognized key means
# Twitter changed the format and the adapter must be reviewed before import.
CONSUMED_TWEET_KEYS = {
    "created_at",
    "entities",
    "extended_entities",
    "favorite_count",
    "full_text",
    "id_str",
    "in_reply_to_screen_name",
    "in_reply_to_status_id_str",
    "lang",
    "retweet_count",
    "retweeted",
    "withheld_in_countries",
}
IGNORED_PUBLIC_TWEET_KEYS = {
    "coordinates",
    "display_text_range",
    "edit_info",
    "favorited",
    "geo",
    "id",
    "in_reply_to_status_id",
    "in_reply_to_user_id",
    "in_reply_to_user_id_str",
    "place",
    "possibly_sensitive",
    "source",
    "truncated",
}
KNOWN_TWEET_KEYS = CONSUMED_TWEET_KEYS | IGNORED_PUBLIC_TWEET_KEYS


class TwitterImportError(ValueError):
    """Raised when archive shape or content cannot be imported safely."""


@dataclass(frozen=True)
class TweetLink:
    short_url: str
    expanded_url: str


@dataclass(frozen=True)
class TweetNode:
    source_id: str
    created_at: datetime
    text: str
    language: str | None
    parent_id: str | None
    parent_handle: str | None
    tags: tuple[str, ...]
    links: tuple[TweetLink, ...]
    likes: int
    reposts: int


@dataclass(frozen=True)
class ImportResult:
    objects: tuple[dict[str, Any], ...]
    exclusions: dict[str, tuple[str, ...]]
    source_sha256: str
    expanded_links: int
    unresolved_short_links: int
    unresolved_urls: tuple[str, ...] = field(repr=False)
    cached_links_applied: int = 0

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
            "sourceSha256": self.source_sha256,
            "expandedLinks": self.expanded_links,
            "unresolvedShortLinks": len(self.unresolved_urls),
            "unresolvedShortLinkOccurrences": self.unresolved_short_links,
            "cachedLinksApplied": self.cached_links_applied,
            "privateValuesEmitted": False,
        }


def _tweet_member(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    matches = [
        item
        for item in archive.infolist()
        if not item.is_dir()
        and PurePosixPath(item.filename).name == TWEET_MEMBER_NAME
        and "data" in PurePosixPath(item.filename).parts
    ]
    if len(matches) != 1:
        raise TwitterImportError(f"expected exactly one Twitter tweets dataset; found {len(matches)}")
    return matches[0]


def _decode_assignment(raw: bytes) -> list[Any]:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TwitterImportError("tweets dataset is not UTF-8") from error
    marker = text.find(JS_ASSIGNMENT_MARKER)
    if marker < 0 or not text[:marker].strip().startswith("window.YTD.tweets"):
        raise TwitterImportError("unrecognized Twitter tweets.js wrapper")
    try:
        value = json.loads(text[marker + 1 :].strip().rstrip(";"))
    except json.JSONDecodeError as error:
        raise TwitterImportError("tweets dataset contains invalid JSON") from error
    if not isinstance(value, list):
        raise TwitterImportError("Twitter tweets dataset is not a list")
    return value


def read_tweet_wrappers(path: Path) -> tuple[list[Any], str]:
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        member = _tweet_member(archive)
        with archive.open(member) as source:
            chunks: list[bytes] = []
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                chunks.append(chunk)
    return _decode_assignment(b"".join(chunks)), digest.hexdigest()


def schema_summary(path: Path) -> dict[str, Any]:
    wrappers, digest = read_tweet_wrappers(path)
    wrapper_keys: set[str] = set()
    tweet_keys: set[str] = set()
    malformed = 0
    for wrapper in wrappers:
        if not isinstance(wrapper, dict):
            malformed += 1
            continue
        wrapper_keys.update(str(key) for key in wrapper)
        tweet = wrapper.get("tweet")
        if not isinstance(tweet, dict):
            malformed += 1
            continue
        tweet_keys.update(str(key) for key in tweet)
    return {
        "records": len(wrappers),
        "malformedRecords": malformed,
        "wrapperKeys": sorted(wrapper_keys),
        "tweetKeys": sorted(tweet_keys),
        "unknownTweetKeys": sorted(tweet_keys - KNOWN_TWEET_KEYS),
        "tweetsDatasetSha256": digest,
        "contentValuesEmitted": False,
    }


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _opaque_id(source_id: str) -> str:
    return hashlib.sha256(f"twitter:{source_id}".encode()).hexdigest()[:16]


def _reason(exclusions: dict[str, list[str]], source_id: str, reason: str) -> None:
    exclusions.setdefault(_opaque_id(source_id), []).append(reason)


def _count(value: Any, field: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if value is None:
        return 0
    raise TwitterImportError(f"tweet has an invalid {field}")


def _public_http_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _parse_node(raw: Any, exclusions: dict[str, list[str]]) -> TweetNode | None:
    if not isinstance(raw, dict) or set(raw) != {"tweet"} or not isinstance(raw.get("tweet"), dict):
        raise TwitterImportError("unrecognized record wrapper")
    tweet = raw["tweet"]
    unknown = set(tweet) - KNOWN_TWEET_KEYS
    if unknown:
        raise TwitterImportError("unrecognized tweet fields: " + ", ".join(sorted(unknown)))

    source_id = tweet.get("id_str")
    if not isinstance(source_id, str) or not source_id.isdigit():
        raise TwitterImportError("tweet has no valid id_str")
    if _truthy(tweet.get("retweeted")) or str(tweet.get("full_text", "")).startswith("RT @"):
        _reason(exclusions, source_id, "retweet")
        return None
    if tweet.get("withheld_in_countries"):
        _reason(exclusions, source_id, "withheld")
        return None
    if any(tweet.get(field) for field in ("coordinates", "geo", "place")):
        _reason(exclusions, source_id, "location_metadata")
        return None

    text = tweet.get("full_text")
    created = tweet.get("created_at")
    if not isinstance(text, str) or not text.strip():
        _reason(exclusions, source_id, "empty_text")
        return None
    if not isinstance(created, str):
        raise TwitterImportError("tweet has no valid created_at")
    try:
        created_at = datetime.strptime(created, TWITTER_DATE_FORMAT)
    except ValueError as error:
        raise TwitterImportError("tweet has an unrecognized created_at") from error

    parent_id = tweet.get("in_reply_to_status_id_str")
    if parent_id is not None and (not isinstance(parent_id, str) or not parent_id.isdigit()):
        raise TwitterImportError("tweet has an invalid reply parent")
    parent_handle = tweet.get("in_reply_to_screen_name")
    if parent_handle is not None and not isinstance(parent_handle, str):
        raise TwitterImportError("tweet has an invalid reply handle")
    language = tweet.get("lang")
    if language is not None and not isinstance(language, str):
        raise TwitterImportError("tweet has an invalid language")
    entities = tweet.get("entities")
    extended_entities = tweet.get("extended_entities")
    tags: set[str] = set()
    links: dict[str, str] = {}
    if entities is not None:
        if (
            not isinstance(entities, dict)
            or not isinstance(entities.get("hashtags", []), list)
            or not isinstance(entities.get("urls", []), list)
        ):
            raise TwitterImportError("tweet has invalid entities")
        for hashtag in entities.get("hashtags", []):
            if not isinstance(hashtag, dict) or not isinstance(hashtag.get("text"), str):
                raise TwitterImportError("tweet has an invalid hashtag")
            value = hashtag["text"].strip().lstrip("#")
            if value:
                tags.add(value)
        for link in entities.get("urls", []):
            if not isinstance(link, dict):
                raise TwitterImportError("tweet has an invalid URL entity")
            short_url = _public_http_url(link.get("url"))
            expanded_url = _public_http_url(link.get("expanded_url"))
            if short_url and expanded_url:
                links[short_url] = expanded_url
        media = entities.get("media", [])
        if not isinstance(media, list):
            raise TwitterImportError("tweet has invalid media URL entities")
        for link in media:
            if not isinstance(link, dict):
                raise TwitterImportError("tweet has an invalid media URL entity")
            short_url = _public_http_url(link.get("url"))
            expanded_url = _public_http_url(link.get("expanded_url"))
            if short_url and expanded_url:
                links[short_url] = expanded_url
    if extended_entities is not None:
        if not isinstance(extended_entities, dict) or not isinstance(extended_entities.get("media", []), list):
            raise TwitterImportError("tweet has invalid extended media entities")
        for link in extended_entities.get("media", []):
            if not isinstance(link, dict):
                raise TwitterImportError("tweet has an invalid extended media URL entity")
            short_url = _public_http_url(link.get("url"))
            expanded_url = _public_http_url(link.get("expanded_url"))
            if short_url and expanded_url:
                links[short_url] = expanded_url
    return TweetNode(
        source_id,
        created_at,
        text,
        language,
        parent_id,
        parent_handle,
        tuple(sorted(tags, key=lambda value: (value.casefold(), value))),
        tuple(TweetLink(short, expanded) for short, expanded in sorted(links.items())),
        _count(tweet.get("favorite_count"), "favorite_count"),
        _count(tweet.get("retweet_count"), "retweet_count"),
    )


def _load_overrides(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TwitterImportError("override manifest is not valid JSON") from error
    if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("roots"), dict):
        raise TwitterImportError("override manifest must contain version=1 and a roots object")
    allowed = {"post", "storm", "exclude"}
    overrides = value["roots"]
    if any(not isinstance(key, str) or action not in allowed for key, action in overrides.items()):
        raise TwitterImportError("override manifest contains an invalid root action")
    return overrides


URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
MARKDOWN_LINK_PATTERN = re.compile(r"\[(https?://[^\]\s]+)\]\((https?://[^)\s]+)\)")
TCO_PATTERN = re.compile(r"https?://t\.co/[A-Za-z0-9]+")


def _expanded_text(node: TweetNode) -> str:
    # Twitter stores plain text containing HTML entities. Decode that transport
    # encoding once, then escape once when producing HTML below.
    text = html.unescape(node.text).replace("\r\n", "\n").replace("\r", "\n")
    text = MARKDOWN_LINK_PATTERN.sub(
        lambda match: match.group(1) if match.group(1) == match.group(2) else match.group(0),
        text,
    )
    # Some archived expanded URLs are themselves t.co links. Iterate so an
    # archive hop and a cached network hop both collapse to the final target.
    for _ in range(len(node.links) + 1):
        expanded = text
        for link in node.links:
            expanded = expanded.replace(link.short_url, link.expanded_url)
        if expanded == text:
            break
        text = expanded
    return text


def _linkify(text: str) -> str:
    output: list[str] = []
    cursor = 0
    for match in URL_PATTERN.finditer(text):
        output.append(html.escape(text[cursor : match.start()]))
        raw = match.group(0)
        url = raw.rstrip(".,;:!?)]}")
        trailing = raw[len(url) :]
        escaped_text = html.escape(url)
        if _public_http_url(url):
            escaped_url = html.escape(url, quote=True)
            output.append(f'<a href="{escaped_url}" rel="nofollow noopener">{escaped_text}</a>')
        else:
            output.append(escaped_text)
        output.append(html.escape(trailing))
        cursor = match.end()
    output.append(html.escape(text[cursor:]))
    return "".join(output).replace("\n", "<br>\n")


def _safe_html(node: TweetNode) -> str:
    return "<p>" + _linkify(_expanded_text(node)) + "</p>"


def _part(node: TweetNode, depth: int) -> dict[str, Any]:
    expanded_text = _expanded_text(node)
    result: dict[str, Any] = {
        "sourceId": node.source_id,
        "date": node.created_at.isoformat(),
        "contentText": expanded_text,
        "contentHtml": _safe_html(node),
        "depth": depth,
        "metrics": {"likes": node.likes, "reposts": node.reposts},
    }
    if node.language:
        result["language"] = node.language
    if node.parent_id:
        result["replyToSourceId"] = node.parent_id
    if node.tags:
        result["tags"] = list(node.tags)
    return result


def _canonical(kind: str, nodes: list[TweetNode], persona: str, handle: str, digest: str) -> dict[str, Any]:
    root = nodes[0]
    expanded_text = _expanded_text(root)
    result: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "socialKind": kind,
        "source": "twitter",
        "persona": persona,
        "sourceId": root.source_id,
        "date": root.created_at.isoformat(),
        "canonicalUrl": f"https://twitter.com/{handle}/status/{root.source_id}",
        "contentText": expanded_text,
        "contentHtml": _safe_html(root),
        "metrics": {"likes": root.likes, "reposts": root.reposts},
        "import": {"adapter": "twitter-v1", "tweetsDatasetSha256": digest},
    }
    if root.language:
        result["language"] = root.language
    combined_tags = sorted(
        {tag for node in nodes for tag in node.tags},
        key=lambda value: (value.casefold(), value),
    )
    if combined_tags:
        result["tags"] = combined_tags
    if kind == "storm":
        depths: dict[str, int] = {root.source_id: 0}
        for node in nodes[1:]:
            if not node.parent_id or node.parent_id not in depths:
                raise TwitterImportError("storm parts are not in parent-before-child order")
            depths[node.source_id] = depths[node.parent_id] + 1
        result["parts"] = [_part(node, depths[node.source_id]) for node in nodes]
    return result


def normalize(
    path: Path,
    *,
    persona: str,
    owner_handle: str,
    assume_public: bool,
    overrides_path: Path | None = None,
    link_cache: dict[str, str] | None = None,
) -> ImportResult:
    if not assume_public:
        raise TwitterImportError("Twitter visibility is absent from the archive; --assume-public is required")
    handle = owner_handle.removeprefix("@").strip()
    if not handle or not persona.strip():
        raise TwitterImportError("persona and owner handle are required")

    wrappers, digest = read_tweet_wrappers(path)
    exclusions: dict[str, list[str]] = {}
    nodes: dict[str, TweetNode] = {}
    for raw in wrappers:
        node = _parse_node(raw, exclusions)
        if node is None:
            continue
        if node.source_id in nodes:
            _reason(exclusions, node.source_id, "duplicate")
            continue
        nodes[node.source_id] = node

    cached_links_applied = 0
    if link_cache:
        for source_id, node in tuple(nodes.items()):
            archive_expanded_text = _expanded_text(node)
            merged = {link.short_url: link.expanded_url for link in node.links}
            applied = 0
            for short_url, target in link_cache.items():
                if short_url in archive_expanded_text and merged.get(short_url) != target:
                    merged[short_url] = target
                    applied += 1
            if applied:
                nodes[source_id] = replace(
                    node,
                    links=tuple(TweetLink(short, target) for short, target in sorted(merged.items())),
                )
                cached_links_applied += applied

    validity: dict[str, bool] = {}
    visiting: set[str] = set()

    def valid(node: TweetNode) -> bool:
        if node.source_id in validity:
            return validity[node.source_id]
        if node.source_id in visiting:
            _reason(exclusions, node.source_id, "reply_cycle")
            validity[node.source_id] = False
            return False
        if node.parent_id is None:
            validity[node.source_id] = True
            return True
        if node.parent_id not in nodes:
            reason = "missing_ancestor"
            if node.parent_handle and node.parent_handle.casefold() != handle.casefold():
                reason = "external_context"
            _reason(exclusions, node.source_id, reason)
            validity[node.source_id] = False
            return False
        if node.parent_handle and node.parent_handle.casefold() != handle.casefold():
            _reason(exclusions, node.source_id, "external_context")
            validity[node.source_id] = False
            return False
        visiting.add(node.source_id)
        parent_valid = valid(nodes[node.parent_id])
        visiting.discard(node.source_id)
        if not parent_valid:
            _reason(exclusions, node.source_id, "excluded_ancestor")
        validity[node.source_id] = parent_valid
        return parent_valid

    valid_nodes = {key: node for key, node in nodes.items() if valid(node)}
    children: dict[str, list[TweetNode]] = defaultdict(list)
    roots: list[TweetNode] = []
    for node in valid_nodes.values():
        if node.parent_id and node.parent_id in valid_nodes:
            children[node.parent_id].append(node)
        else:
            roots.append(node)
    for values in children.values():
        values.sort(key=lambda node: (node.created_at, node.source_id))
    roots.sort(key=lambda node: (node.created_at, node.source_id))

    overrides = _load_overrides(overrides_path)
    unknown_override_ids = set(overrides) - set(valid_nodes)
    if unknown_override_ids:
        raise TwitterImportError("override manifest refers to an unknown or excluded source ID")

    objects: list[dict[str, Any]] = []
    published_nodes: list[TweetNode] = []
    for root in roots:
        collected: list[TweetNode] = []
        stack = [root]
        while stack:
            current = stack.pop()
            collected.append(current)
            stack.extend(reversed(children.get(current.source_id, [])))
        action = overrides.get(root.source_id)
        if action == "exclude":
            for node in collected:
                _reason(exclusions, node.source_id, "manual_exclusion")
            continue

        inferred = "post" if len(collected) == 1 else "storm"
        kind = action or inferred
        if kind == "post" and len(collected) > 1:
            for node in collected[1:]:
                _reason(exclusions, node.source_id, "manual_root_only")
            collected = collected[:1]
        published_nodes.extend(collected)
        objects.append(_canonical(kind, collected, persona.strip(), handle, digest))

    objects.sort(key=lambda item: (item["date"], item["sourceId"]))
    frozen_exclusions = {key: tuple(sorted(set(value))) for key, value in sorted(exclusions.items())}
    expanded_links = sum(
        1
        for node in published_nodes
        for link in node.links
        if TCO_PATTERN.fullmatch(link.short_url)
    )
    unresolved_occurrences = sum(len(TCO_PATTERN.findall(_expanded_text(node))) for node in published_nodes)
    unresolved_urls = tuple(
        sorted({url for node in published_nodes for url in TCO_PATTERN.findall(_expanded_text(node))})
    )
    return ImportResult(
        tuple(objects),
        frozen_exclusions,
        digest,
        expanded_links,
        unresolved_occurrences,
        unresolved_urls,
        cached_links_applied,
    )


def write_staging(result: ImportResult, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    records = output / "records"
    records.mkdir()
    for item in result.objects:
        target = records / f"twitter-{item['persona']}-{item['sourceId']}.json"
        target.write_text(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "report.json").write_text(
        json.dumps(result.report(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output / "exclusions.json").write_text(
        json.dumps(result.exclusions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
