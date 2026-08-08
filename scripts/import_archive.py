#!/usr/bin/env python3
"""Privacy-preserving entry points for future social archive imports.

Only structural ZIP inspection is implemented. Content import deliberately
fails closed until the field allowlist and synthetic-fixture tests land.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import json
import sys
import zipfile

from social_archive.twitter import (
    TwitterImportError,
    normalize as normalize_twitter,
    schema_summary as twitter_schema_summary,
    write_staging,
)
from social_archive.hugo_preview import compile_preview
from social_archive.hugo_preview import PreviewCompileError
from social_archive import link_cache
from social_archive.mastodon import (
    MastodonImportError,
    normalize as normalize_mastodon,
    schema_summary as mastodon_schema_summary,
    write_staging as write_mastodon_staging,
)
from social_archive.public_corpus import (
    PublicCorpusError,
    load_and_validate as validate_public_corpus_data,
    write_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_SOURCES = ("twitter", "mastodon")


class SafetyError(ValueError):
    """Raised when an input crosses the repository privacy boundary."""


def private_input_path(raw_path: str) -> Path:
    """Resolve an input and reject anything located inside this repository."""
    path = Path(raw_path).expanduser().resolve(strict=True)
    if path == REPOSITORY_ROOT or REPOSITORY_ROOT in path.parents:
        raise SafetyError("private input must remain outside the repository")
    if not path.is_file():
        raise SafetyError("private input must be a regular file")
    return path


def external_output_path(raw_path: str) -> Path:
    """Resolve a not-yet-created staging path outside the repository."""
    path = Path(raw_path).expanduser().resolve(strict=False)
    if path == REPOSITORY_ROOT or REPOSITORY_ROOT in path.parents:
        raise SafetyError("staging output must remain outside the repository")
    if path.exists():
        raise SafetyError("staging output must not already exist")
    if not path.parent.is_dir():
        raise SafetyError("staging output parent does not exist")
    return path


def quarantined_preview_path() -> Path:
    """Return the one repository path allowed to contain real-data drafts."""
    path = REPOSITORY_ROOT / "content" / "posts" / "imported"
    ignore_rule = "/content/posts/imported/"
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
    if ignore_rule not in gitignore.splitlines():
        raise SafetyError("private preview path is not protected by .gitignore")
    return path


def twitter_link_cache_path() -> Path:
    return REPOSITORY_ROOT / "var" / "twitter-link-cache.json"


def public_corpus_path() -> Path:
    return REPOSITORY_ROOT / "assets" / "public_archive"


def inspect_archive(source: str, raw_path: str) -> int:
    """Report only aggregate ZIP structure; never print member paths or data."""
    path = private_input_path(raw_path)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")

    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        suffixes = Counter(Path(item.filename).suffix.lower() or "[none]" for item in members)
        unpacked_bytes = sum(item.file_size for item in members)

    print(f"source={source}")
    print(f"members={len(members)}")
    print(f"unpacked_bytes={unpacked_bytes}")
    print("member_types=" + ",".join(f"{suffix}:{count}" for suffix, count in sorted(suffixes.items())))
    print("content_read=false")
    print("output_written=false")
    return 0


def not_implemented(command: str) -> int:
    print(
        f"error: {command} is intentionally disabled until its allowlist and "
        "synthetic-fixture safety tests are implemented",
        file=sys.stderr,
    )
    return 2


def archive_schema(source: str, raw_path: str) -> int:
    path = private_input_path(raw_path)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")
    summary = twitter_schema_summary(path) if source == "twitter" else mastodon_schema_summary(path)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def import_twitter(args: argparse.Namespace) -> int:
    path = private_input_path(args.archive)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")
    overrides = Path(args.overrides).expanduser().resolve(strict=True) if args.overrides else None
    result = normalize_twitter(
        path,
        persona=args.persona,
        owner_handle=args.owner_handle,
        assume_public=args.assume_public,
        overrides_path=overrides,
        link_cache=link_cache.load(twitter_link_cache_path()),
    )
    print(json.dumps(result.report(), indent=2, sort_keys=True))
    if args.dry_run:
        print("output_written=false")
        return 0
    output = external_output_path(args.output)
    write_staging(result, output)
    print(f"staged_records={len(result.objects)}")
    return 0


def preview_twitter(args: argparse.Namespace) -> int:
    path = private_input_path(args.archive)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")
    overrides = Path(args.overrides).expanduser().resolve(strict=True) if args.overrides else None
    result = normalize_twitter(
        path,
        persona=args.persona,
        owner_handle=args.owner_handle,
        assume_public=args.assume_public,
        overrides_path=overrides,
        link_cache=link_cache.load(twitter_link_cache_path()),
    )
    compiled = compile_preview(result, quarantined_preview_path(), source="twitter")
    print(json.dumps(compiled.as_dict(), indent=2, sort_keys=True))
    print("git_ignored=true")
    return 0


def import_mastodon(args: argparse.Namespace) -> int:
    path = private_input_path(args.archive)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")
    result = normalize_mastodon(
        path,
        persona=args.persona,
        owner_controlled=args.owner_controlled,
    )
    print(json.dumps(result.report(), indent=2, sort_keys=True))
    if args.dry_run:
        print("output_written=false")
        return 0
    output = external_output_path(args.output)
    write_mastodon_staging(result, output)
    print(f"staged_records={len(result.objects)}")
    return 0


def preview_mastodon(args: argparse.Namespace) -> int:
    path = private_input_path(args.archive)
    if not zipfile.is_zipfile(path):
        raise SafetyError("input is not a ZIP archive")
    result = normalize_mastodon(
        path,
        persona=args.persona,
        owner_controlled=args.owner_controlled,
    )
    compiled = compile_preview(result, quarantined_preview_path(), source="mastodon")
    print(json.dumps(compiled.as_dict(), indent=2, sort_keys=True))
    print("git_ignored=true")
    return 0


def resolve_twitter_links(args: argparse.Namespace) -> int:
    path = private_input_path(args.archive)
    existing = link_cache.load(twitter_link_cache_path())
    result = normalize_twitter(
        path,
        persona=args.persona,
        owner_handle=args.owner_handle,
        assume_public=args.assume_public,
        link_cache=existing,
    )
    resolved = link_cache.resolve(result.unresolved_urls, workers=args.workers)
    existing.update(resolved)
    link_cache.save(twitter_link_cache_path(), existing)
    print(json.dumps({
        "attempted": len(result.unresolved_urls),
        "cacheUnresolvedOverlap": len(set(existing) & set(result.unresolved_urls)),
        "resolved": len(resolved),
        "stillUnresolved": len(result.unresolved_urls) - len(resolved),
        "cacheEntries": len(existing),
        "urlsEmitted": False,
    }, indent=2, sort_keys=True))
    return 0


def promote_public_corpus(args: argparse.Namespace) -> int:
    twitter_path = private_input_path(args.twitter_archive)
    mastodon_path = private_input_path(args.mastodon_archive)
    if not zipfile.is_zipfile(twitter_path) or not zipfile.is_zipfile(mastodon_path):
        raise SafetyError("public corpus inputs must be ZIP archives")
    twitter_result = normalize_twitter(
        twitter_path,
        persona=args.persona,
        owner_handle=args.owner_handle,
        assume_public=args.assume_twitter_public,
        link_cache=link_cache.load(twitter_link_cache_path()),
    )
    mastodon_result = normalize_mastodon(
        mastodon_path,
        persona=args.persona,
        owner_controlled=args.owner_controlled,
    )
    report = write_corpus(
        (*twitter_result.objects, *mastodon_result.objects),
        public_corpus_path(),
        {
            "twitter": twitter_result.source_sha256,
            "mastodon": mastodon_result.source_sha256,
        },
    )
    report["recordsBySource"] = {
        "twitter": len(twitter_result.objects),
        "mastodon": len(mastodon_result.objects),
    }
    report["rawArchivesCopied"] = False
    report["generatedHtmlTracked"] = False
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def validate_public_corpus() -> int:
    print(json.dumps(validate_public_corpus_data(public_corpus_path()), indent=2, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subcommands = result.add_subparsers(dest="command", required=True)

    inspect = subcommands.add_parser("inspect", help="inspect aggregate archive structure")
    inspect.add_argument("--source", choices=SUPPORTED_SOURCES, required=True)
    inspect.add_argument("--archive", required=True)

    schema = subcommands.add_parser("schema", help="report archive schema keys without values")
    schema.add_argument("--source", choices=SUPPORTED_SOURCES, required=True)
    schema.add_argument("--archive", required=True)

    bulk_import = subcommands.add_parser("import", help="normalize a reviewed archive")
    bulk_import.add_argument("--source", choices=SUPPORTED_SOURCES, required=True)
    bulk_import.add_argument("--archive", required=True)
    bulk_import.add_argument("--persona")
    bulk_import.add_argument("--owner-handle")
    bulk_import.add_argument("--assume-public", action="store_true")
    bulk_import.add_argument("--owner-controlled", action="store_true")
    bulk_import.add_argument("--overrides")
    destination = bulk_import.add_mutually_exclusive_group(required=False)
    destination.add_argument("--dry-run", action="store_true")
    destination.add_argument("--output")

    preview = subcommands.add_parser("preview", help="compile ignored local Hugo drafts")
    preview.add_argument("--source", choices=SUPPORTED_SOURCES, required=True)
    preview.add_argument("--archive", required=True)
    preview.add_argument("--persona", required=True)
    preview.add_argument("--owner-handle")
    preview.add_argument("--assume-public", action="store_true")
    preview.add_argument("--owner-controlled", action="store_true")
    preview.add_argument("--overrides")

    resolve_links = subcommands.add_parser("resolve-links", help="resolve and cache remaining t.co redirects")
    resolve_links.add_argument("--source", choices=("twitter",), required=True)
    resolve_links.add_argument("--archive", required=True)
    resolve_links.add_argument("--persona", required=True)
    resolve_links.add_argument("--owner-handle", required=True)
    resolve_links.add_argument("--assume-public", action="store_true")
    resolve_links.add_argument("--workers", type=int, default=8, choices=range(1, 17))

    ingest_one = subcommands.add_parser("ingest-one", help="reserved one-post import stub")
    ingest_one.add_argument("--source", choices=("mastodon",), required=True)
    ingest_one.add_argument("--record", required=True)

    promote = subcommands.add_parser("promote-public", help="write the tracked public-only corpus")
    promote.add_argument("--twitter-archive", required=True)
    promote.add_argument("--mastodon-archive", required=True)
    promote.add_argument("--persona", required=True)
    promote.add_argument("--owner-handle", required=True)
    promote.add_argument("--assume-twitter-public", action="store_true")
    promote.add_argument("--owner-controlled", action="store_true")

    subcommands.add_parser("validate-public", help="validate the tracked public-only corpus")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return inspect_archive(args.source, args.archive)
        if args.command == "schema":
            return archive_schema(args.source, args.archive)
        if args.command == "import":
            if not args.persona:
                raise SafetyError("archive import requires --persona")
            if not args.dry_run and not args.output:
                raise SafetyError("archive import requires --dry-run or --output")
            if args.source == "mastodon":
                return import_mastodon(args)
            if not args.owner_handle:
                raise SafetyError("Twitter import requires --owner-handle")
            return import_twitter(args)
        if args.command == "preview":
            if args.source == "mastodon":
                return preview_mastodon(args)
            if not args.owner_handle:
                raise SafetyError("Twitter preview requires --owner-handle")
            return preview_twitter(args)
        if args.command == "resolve-links":
            return resolve_twitter_links(args)
        if args.command == "ingest-one":
            private_input_path(args.record)
            return not_implemented("single-post ingest")
        if args.command == "promote-public":
            return promote_public_corpus(args)
        if args.command == "validate-public":
            return validate_public_corpus()
    except (
        OSError, SafetyError, TwitterImportError, MastodonImportError,
        PreviewCompileError, PublicCorpusError, zipfile.BadZipFile,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
