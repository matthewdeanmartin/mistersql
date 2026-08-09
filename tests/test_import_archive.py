from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_archive.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("import_archive", SCRIPT)
assert SPEC and SPEC.loader
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)

from social_archive.twitter import TwitterImportError, normalize, schema_summary, write_staging
from social_archive.hugo_preview import SENTINEL_NAME, compile_preview
from social_archive.mastodon import (
    MastodonImportError,
    normalize as normalize_mastodon,
    schema_summary as mastodon_schema_summary,
)
from social_archive.public_corpus import (
    PublicCorpusError,
    load_and_validate,
    public_record,
    write_corpus,
)


def tweet(
    source_id: str,
    text: str,
    date: str,
    *,
    parent: str | None = None,
    parent_handle: str | None = None,
    **extra: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "id_str": source_id,
        "full_text": text,
        "created_at": date,
        "lang": "en",
        "in_reply_to_status_id_str": parent,
        "in_reply_to_screen_name": parent_handle,
        "retweeted": False,
        "entities": {"hashtags": []},
    }
    value.update(extra)
    return {"tweet": value}


def write_twitter_zip(path: Path, records: list[dict[str, object]]) -> None:
    payload = "window.YTD.tweets.part0 = " + json.dumps(records)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("data/tweets.js", payload)
        archive.writestr("data/direct-messages.js", "PRIVATE_FIXTURE_CANARY")


PUBLIC = "https://www.w3.org/ns/activitystreams#Public"
ACTOR = "https://social.example/users/owner"


def mastodon_create(
    source_id: str,
    content: str,
    date: str,
    *,
    parent: str | None = None,
    public_to: bool = True,
    **extra: object,
) -> dict[str, object]:
    object_id = f"https://social.example/users/owner/statuses/{source_id}"
    obj: dict[str, object] = {
        "id": object_id,
        "type": "Note",
        "attributedTo": ACTOR,
        "content": content,
        "contentMap": {"en": content},
        "published": date,
        "url": object_id,
        "to": [PUBLIC] if public_to else [f"{ACTOR}/followers"],
        "cc": [f"{ACTOR}/followers"] if public_to else [],
        "inReplyTo": parent,
        "tag": [],
        "attachment": [],
        "likes": {"type": "Collection", "totalItems": 0},
        "shares": {"type": "Collection", "totalItems": 0},
    }
    obj.update(extra)
    return {
        "id": f"https://social.example/users/owner/activities/{source_id}",
        "type": "Create",
        "actor": ACTOR,
        "published": date,
        "to": obj["to"],
        "cc": obj["cc"],
        "object": obj,
    }


def write_mastodon_zip(path: Path, records: list[dict[str, object]]) -> None:
    outbox = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{ACTOR}/outbox",
        "type": "OrderedCollection",
        "totalItems": len(records),
        "orderedItems": records,
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("outbox.json", json.dumps(outbox))
        archive.writestr("actor.json", json.dumps({"type": "Person", "summary": "PRIVATE_FIXTURE_CANARY"}))
        archive.writestr("likes.json", json.dumps({"type": "OrderedCollection", "orderedItems": ["PRIVATE_FIXTURE_CANARY"]}))


class ImportSafetyTests(unittest.TestCase):
    def test_hugo_content_adapter_sets_page_date_through_dates_map(self) -> None:
        adapter = (SCRIPT.parents[1] / "content" / "posts" / "_content.gotmpl").read_text(
            encoding="utf-8"
        )
        self.assertIn('"dates" (dict "date" (time.AsTime $record.date))', adapter)

    def test_rejects_private_input_inside_repository(self) -> None:
        with self.assertRaisesRegex(IMPORTER.SafetyError, "outside the repository"):
            IMPORTER.private_input_path(str(Path(__file__).resolve()))

    def test_rejects_staging_output_inside_repository(self) -> None:
        with self.assertRaisesRegex(IMPORTER.SafetyError, "outside the repository"):
            IMPORTER.external_output_path(str(Path(__file__).parent / "staging"))

    def test_aggregate_inspection_does_not_emit_member_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, [])
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(IMPORTER.inspect_archive("twitter", str(archive_path)), 0)
            rendered = output.getvalue()
            self.assertIn("content_read=false", rendered)
            self.assertNotIn("direct-messages", rendered)
            self.assertNotIn("PRIVATE_FIXTURE_CANARY", rendered)

    def test_schema_summary_emits_keys_not_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(
                archive_path,
                [tweet("1", "PRIVATE_FIXTURE_CANARY", "Wed Jan 01 00:00:00 +0000 2020")],
            )
            summary = json.dumps(schema_summary(archive_path), sort_keys=True)
            self.assertIn("full_text", summary)
            self.assertNotIn("PRIVATE_FIXTURE_CANARY", summary)

    def test_requires_explicit_public_visibility_assumption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, [])
            with self.assertRaisesRegex(TwitterImportError, "assume-public"):
                normalize(
                    archive_path,
                    persona="owner",
                    owner_handle="owner",
                    assume_public=False,
                )

    def test_classifies_linear_and_branched_storms_and_exclusions(self) -> None:
        records = [
            tweet("1", "Standalone #One", "Wed Jan 01 00:00:00 +0000 2020", entities={"hashtags": [{"text": "One"}]}),
            tweet("10", "Storm one", "Thu Jan 02 00:00:00 +0000 2020"),
            tweet("11", "Storm two", "Thu Jan 02 00:05:00 +0000 2020", parent="10", parent_handle="owner"),
            tweet("12", "Storm three", "Thu Jan 02 00:10:00 +0000 2020", parent="11", parent_handle="owner"),
            tweet("20", "Branched storm root", "Fri Jan 03 00:00:00 +0000 2020"),
            tweet("21", "Follow-up A", "Fri Jan 03 00:05:00 +0000 2020", parent="20", parent_handle="owner"),
            tweet("22", "Follow-up B", "Fri Jan 03 00:06:00 +0000 2020", parent="20", parent_handle="owner"),
            tweet("30", "Missing self parent", "Sat Jan 04 00:00:00 +0000 2020", parent="999", parent_handle="owner"),
            tweet("40", "External parent", "Sun Jan 05 00:00:00 +0000 2020", parent="888", parent_handle="someone_else"),
            tweet("50", "RT @example: repost", "Mon Jan 06 00:00:00 +0000 2020", retweeted=True),
            tweet("60", "Located", "Tue Jan 07 00:00:00 +0000 2020", coordinates={"coordinates": [1, 2]}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            result = normalize(
                archive_path,
                persona="owner",
                owner_handle="@owner",
                assume_public=True,
            )

        self.assertEqual([item["socialKind"] for item in result.objects], ["post", "storm", "storm"])
        self.assertEqual([part["sourceId"] for part in result.objects[1]["parts"]], ["10", "11", "12"])
        self.assertEqual([part["sourceId"] for part in result.objects[2]["parts"]], ["20", "21", "22"])
        self.assertEqual([part["depth"] for part in result.objects[2]["parts"]], [0, 1, 1])
        self.assertEqual(result.objects[0]["tags"], ["One"])
        self.assertEqual(result.report()["includedRecords"], 7)
        reasons = result.report()["exclusionReasons"]
        self.assertEqual(reasons["missing_ancestor"], 1)
        self.assertEqual(reasons["external_context"], 1)
        self.assertEqual(reasons["retweet"], 1)
        self.assertEqual(reasons["location_metadata"], 1)
        self.assertNotIn("Missing self parent", json.dumps(result.report()))

    def test_unknown_fields_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(
                archive_path,
                [tweet("1", "Text", "Wed Jan 01 00:00:00 +0000 2020", surprise_private_field="nope")],
            )
            with self.assertRaisesRegex(TwitterImportError, "unrecognized tweet fields"):
                normalize(archive_path, persona="owner", owner_handle="owner", assume_public=True)

    def test_html_is_escaped_and_missing_middle_excludes_descendants(self) -> None:
        records = [
            tweet("1", "<script>alert('no')</script>", "Wed Jan 01 00:00:00 +0000 2020"),
            tweet("3", "Third without second", "Wed Jan 01 00:10:00 +0000 2020", parent="2", parent_handle="owner"),
            tweet("4", "Fourth", "Wed Jan 01 00:11:00 +0000 2020", parent="3", parent_handle="owner"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            result = normalize(archive_path, persona="owner", owner_handle="owner", assume_public=True)
        self.assertNotIn("<script>", result.objects[0]["contentHtml"])
        self.assertIn("&lt;script&gt;", result.objects[0]["contentHtml"])
        reasons = result.report()["exclusionReasons"]
        self.assertEqual(reasons["missing_ancestor"], 1)
        self.assertEqual(reasons["excluded_ancestor"], 1)

    def test_expands_archived_links_decodes_once_and_preserves_metrics(self) -> None:
        short = "https://t.co/LjrMeBOFoH"
        expanded = "https://example.test/a?one=1&two=2"
        records = [
            tweet(
                "1",
                f"[{short}]({short}) Fish &amp; chips",
                "Wed Jan 01 00:00:00 +0000 2020",
                favorite_count="42",
                retweet_count="7",
                entities={
                    "hashtags": [],
                    "urls": [{"url": short, "expanded_url": expanded, "display_url": "example.test/a"}],
                },
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            result = normalize(archive_path, persona="owner", owner_handle="owner", assume_public=True)
        item = result.objects[0]
        self.assertNotIn("t.co", item["contentText"])
        self.assertIn(expanded, item["contentText"])
        self.assertIn(f'href="https://example.test/a?one=1&amp;two=2"', item["contentHtml"])
        self.assertIn("Fish &amp; chips", item["contentHtml"])
        self.assertNotIn("&amp;amp;", item["contentHtml"])
        self.assertEqual(item["metrics"], {"likes": 42, "reposts": 7})
        self.assertEqual(result.report()["expandedLinks"], 1)
        self.assertEqual(result.report()["unresolvedShortLinks"], 0)

    def test_applies_cached_redirect_to_unresolved_short_link(self) -> None:
        short = "https://t.co/CacheMe123"
        expanded = "https://example.test/cached"
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(
                archive_path,
                [tweet("1", short, "Wed Jan 01 00:00:00 +0000 2020")],
            )
            result = normalize(
                archive_path,
                persona="owner",
                owner_handle="owner",
                assume_public=True,
                link_cache={short: expanded},
            )
        self.assertIn(expanded, result.objects[0]["contentHtml"])
        self.assertEqual(result.report()["expandedLinks"], 1)
        self.assertEqual(result.report()["unresolvedShortLinks"], 0)

    def test_malformed_expanded_url_remains_text_not_a_link(self) -> None:
        short = "https://t.co/BadUrl123"
        malformed = "https://[broken/path"
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(
                archive_path,
                [tweet("1", short, "Wed Jan 01 00:00:00 +0000 2020")],
            )
            result = normalize(
                archive_path,
                persona="owner",
                owner_handle="owner",
                assume_public=True,
                link_cache={short: malformed},
            )
        self.assertIn(malformed, result.objects[0]["contentText"])
        self.assertNotIn("<a ", result.objects[0]["contentHtml"])

    def test_reviewed_override_can_mark_a_chain_as_storm(self) -> None:
        records = [
            tweet("1", "Part one", "Wed Jan 01 00:00:00 +0000 2020"),
            tweet("2", "Part two much later", "Thu Jan 02 00:00:00 +0000 2020", parent="1", parent_handle="owner"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "synthetic.zip"
            overrides = root / "overrides.json"
            write_twitter_zip(archive_path, records)
            overrides.write_text(json.dumps({"version": 1, "roots": {"1": "storm"}}), encoding="utf-8")
            result = normalize(
                archive_path,
                persona="owner",
                owner_handle="owner",
                assume_public=True,
                overrides_path=overrides,
            )
        self.assertEqual(result.objects[0]["socialKind"], "storm")

    def test_staging_is_deterministic_and_does_not_copy_denied_dataset(self) -> None:
        records = [tweet("1", "Public synthetic text", "Wed Jan 01 00:00:00 +0000 2020")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            result = normalize(archive_path, persona="owner", owner_handle="owner", assume_public=True)
            first = root / "first"
            second = root / "second"
            write_staging(result, first)
            write_staging(result, second)
            first_files = {path.relative_to(first): path.read_bytes() for path in first.rglob("*") if path.is_file()}
            second_files = {path.relative_to(second): path.read_bytes() for path in second.rglob("*") if path.is_file()}
            self.assertEqual(first_files, second_files)
            self.assertNotIn(b"PRIVATE_FIXTURE_CANARY", b"".join(first_files.values()))

    def test_hugo_preview_is_draft_ignored_shape_and_incremental(self) -> None:
        records = [tweet("1", "Preview text", "Wed Jan 01 00:00:00 +0000 2020")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "synthetic.zip"
            output = root / "preview"
            write_twitter_zip(archive_path, records)
            result = normalize(archive_path, persona="owner", owner_handle="owner", assume_public=True)
            first = compile_preview(result, output)
            second = compile_preview(result, output)
            page = (output / "2020" / "twitter-1.html").read_text(encoding="utf-8")
            self.assertTrue((output / SENTINEL_NAME).is_file())
            self.assertEqual((first.changed, first.unchanged), (1, 0))
            self.assertEqual((second.changed, second.unchanged), (0, 1))
            self.assertIn('"draft": true', page)
            self.assertIn('"privatePreview": true', page)
            self.assertIn('"socialMetrics"', page)
            self.assertIn("<p>Preview text</p>", page)

    def test_public_corpus_drops_import_metadata_and_rejects_unknown_fields(self) -> None:
        records = [tweet("1", "Public text", "Wed Jan 01 00:00:00 +0000 2020")]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            normalized = normalize(
                archive_path, persona="owner", owner_handle="owner", assume_public=True
            ).objects[0]
        self.assertIn("import", normalized)
        self.assertNotIn("import", public_record(normalized))
        denied = dict(normalized, privateContactBook="denied")
        with self.assertRaisesRegex(PublicCorpusError, "unknown publication fields"):
            public_record(denied)

    def test_public_corpus_tag_order_has_a_deterministic_case_tiebreaker(self) -> None:
        records = [
            tweet(
                "1",
                "Tags",
                "Wed Jan 01 00:00:00 +0000 2020",
                entities={"hashtags": [{"text": "tag"}, {"text": "Tag"}]},
            )
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_twitter_zip(archive_path, records)
            normalized = normalize(
                archive_path, persona="owner", owner_handle="owner", assume_public=True
            ).objects[0]
        self.assertEqual(normalized["tags"], ["Tag", "tag"])
        self.assertEqual(public_record(normalized)["tags"], ["Tag", "tag"])

    def test_public_corpus_rejects_active_html(self) -> None:
        record = {
            "schemaVersion": 1,
            "socialKind": "post",
            "source": "twitter",
            "persona": "owner",
            "sourceId": "1",
            "date": "2020-01-01T00:00:00Z",
            "contentHtml": '<p onclick="bad()">No</p>',
            "contentText": "No",
            "metrics": {"likes": 0, "reposts": 0},
        }
        with self.assertRaisesRegex(PublicCorpusError, "denied attribute"):
            public_record(record)
        record["contentHtml"] = "<script>No</script>"
        with self.assertRaisesRegex(PublicCorpusError, "denied tag"):
            public_record(record)

    def test_public_corpus_is_deterministic_and_self_validating(self) -> None:
        records = [tweet("1", "Public text", "Wed Jan 01 00:00:00 +0000 2020")]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "synthetic.zip"
            output = root / "public_archive"
            write_twitter_zip(archive_path, records)
            result = normalize(
                archive_path, persona="owner", owner_handle="owner", assume_public=True
            )
            first = write_corpus(result.objects, output, {"twitter": result.source_sha256})
            second = write_corpus(result.objects, output, {"twitter": result.source_sha256})
            validated = load_and_validate(output)
            rendered = b"".join(path.read_bytes() for path in output.rglob("*") if path.is_file())
            self.assertGreater(first["changed"], 0)
            self.assertEqual(second["changed"], 0)
            self.assertEqual(validated["records"], 1)
            self.assertNotIn(b'"import"', rendered)
            self.assertNotIn(b'"draft"', rendered)
            self.assertNotIn(b'"privatePreview"', rendered)
            (output / "unexpected.txt").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(PublicCorpusError, "unexpected file"):
                load_and_validate(output)

    def test_mastodon_requires_owner_controlled_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_mastodon_zip(archive_path, [])
            with self.assertRaisesRegex(MastodonImportError, "owner-controlled"):
                normalize_mastodon(archive_path, persona="owner", owner_controlled=False)

    def test_mastodon_schema_emits_structure_not_private_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_mastodon_zip(
                archive_path,
                [mastodon_create("1", "PRIVATE_FIXTURE_CANARY", "2024-01-01T00:00:00Z")],
            )
            rendered = json.dumps(mastodon_schema_summary(archive_path), sort_keys=True)
        self.assertIn("contentMap", rendered)
        self.assertNotIn("PRIVATE_FIXTURE_CANARY", rendered)

    def test_mastodon_normalizes_public_threads_warnings_polls_and_metrics(self) -> None:
        root_url = "https://social.example/users/owner/statuses/10"
        records = [
            mastodon_create(
                "10",
                '<p>Hello &amp; welcome <script>PRIVATE_FIXTURE_CANARY</script><a href="https://example.test/x?a=1&amp;b=2">link</a></p>',
                "2024-01-01T00:00:00Z",
                summary="A warning",
                sensitive=True,
                tag=[{"type": "Hashtag", "name": "#Python", "href": "https://social.example/tags/python"}],
                likes={"type": "Collection", "totalItems": 12},
                shares={"type": "Collection", "totalItems": 3},
            ),
            mastodon_create("11", "<p>Self reply</p>", "2024-01-01T00:05:00Z", parent=root_url),
            mastodon_create("20", "<p>External reply</p>", "2024-01-02T00:00:00Z", parent="https://elsewhere.example/post/1"),
            mastodon_create("30", "<p>Private</p>", "2024-01-03T00:00:00Z", public_to=False),
            mastodon_create(
                "40",
                "<p>Pick one</p>",
                "2024-01-04T00:00:00Z",
                type="Question",
                oneOf=[
                    {"type": "Note", "name": "A", "replies": {"type": "Collection", "totalItems": 5}},
                    {"type": "Note", "name": "B", "replies": {"type": "Collection", "totalItems": 2}},
                ],
                votersCount=7,
                attachment=[{"type": "Document", "url": "https://social.example/media/ignored.jpg", "mediaType": "image/jpeg"}],
            ),
            {"id": "https://social.example/activities/boost", "type": "Announce", "actor": ACTOR, "object": "https://elsewhere.example/post/2"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "synthetic.zip"
            write_mastodon_zip(archive_path, records)
            result = normalize_mastodon(archive_path, persona="owner", owner_controlled=True)

        self.assertEqual([item["socialKind"] for item in result.objects], ["storm", "post"])
        storm, poll = result.objects
        self.assertEqual([part["sourceId"] for part in storm["parts"]], ["10", "11"])
        self.assertEqual(storm["contentWarning"], "A warning")
        self.assertEqual(storm["tags"], ["Python"])
        self.assertEqual(storm["metrics"], {"likes": 12, "reposts": 3})
        self.assertNotIn("script", storm["contentHtml"])
        self.assertNotIn("PRIVATE_FIXTURE_CANARY", storm["contentHtml"])
        self.assertIn("Hello &amp; welcome", storm["contentHtml"])
        self.assertIn('href="https://example.test/x?a=1&amp;b=2"', storm["contentHtml"])
        self.assertEqual(poll["poll"]["options"][0], {"name": "A", "votes": 5})
        report = result.report()
        self.assertEqual(report["attachmentsIgnored"], 1)
        self.assertEqual(report["exclusionReasons"]["external_context"], 1)
        self.assertEqual(report["exclusionReasons"]["nonpublic_visibility"], 1)
        self.assertEqual(report["exclusionReasons"]["boost"], 1)

    def test_preview_compilation_keeps_other_source_pages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_path = root / "mastodon.zip"
            output = root / "preview"
            write_mastodon_zip(
                archive_path,
                [mastodon_create("1", "<p>Mastodon post</p>", "2024-01-01T00:00:00Z")],
            )
            output.mkdir()
            (output / SENTINEL_NAME).write_text("Generated private preview. Do not commit or publish.\n", encoding="utf-8")
            twitter_page = output / "2020" / "twitter-1.html"
            twitter_page.parent.mkdir()
            twitter_page.write_text("keep", encoding="utf-8")
            result = normalize_mastodon(archive_path, persona="owner", owner_controlled=True)
            first = compile_preview(result, output, source="mastodon")
            second = compile_preview(result, output, source="mastodon")
            twitter_page_kept = twitter_page.is_file()
        self.assertEqual((first.changed, first.removed), (1, 0))
        self.assertEqual((second.changed, second.unchanged), (0, 1))
        self.assertTrue(twitter_page_kept)


if __name__ == "__main__":
    unittest.main()
