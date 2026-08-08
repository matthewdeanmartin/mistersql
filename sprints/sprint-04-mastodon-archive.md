# Sprint 4: Mastodon Archive Import

## Outcome

An owner-controlled Mastodon ActivityPub export can be inspected, normalized,
and compiled into the quarantined Hugo preview with record-level visibility
enforcement and source-scoped incremental updates.

## Implemented

- `make archive-schema SOURCE=mastodon` reports structural keys and counts,
  never content values.
- Only the outbox JSON document is read. Actor profile data, followers,
  following, likes, bookmarks, media bytes, and all other export members are
  denied.
- Public and unlisted `Create` activities containing `Note` or `Question`
  objects normalize into the shared schema.
- Followers-only/direct records, boosts, empty posts, and incomplete external
  conversations are excluded with aggregate reason codes.
- Complete owner-authored self-reply graphs render as unified thread cards,
  including branches.
- Content warnings use native HTML `details`, so disclosure works without
  JavaScript. Polls render as read-only archived results.
- Hashtags, language, timestamps, canonical URLs, likes, and repost/boost
  totals are preserved. Attachment metadata is counted but no media is opened
  or copied.
- Preview reconciliation is source-scoped. A periodic Mastodon export changes
  only changed/stale Mastodon pages and leaves Twitter pages byte-identical.

## Real archive baseline

- Outbox activities: 11,609
- Authored `Create` activities: 10,274
- Boosts excluded: 1,335
- Non-public records excluded: 228
- Included authored records: 6,009
- Hugo feed objects: 4,800
- Standalone posts: 4,011
- Complete self-reply threads: 789
- Content-warning roots: 63
- Poll roots: 89
- Attachment references ignored: 2,176
- External/missing-context replies excluded: 3,879
- Descendants of excluded context: 153

## Combined archive build optimization

With all 15,285 Twitter and Mastodon feed objects present, a clean minified
build initially took 94.55 seconds and emitted 18,612 files (179.9 MB).
Caching the site-wide rails/head additions, keeping the complete pagination
only on the home timeline, and limiting RSS to the site feed reduced the same
build to 31.21 seconds and 17,383 files (139.6 MB). Hugo already parallelizes
page rendering internally; no multi-process output merge is required.

## Safety status

The raw ZIP remains outside the repository. Generated Mastodon preview pages
are ignored drafts under the sentinel-protected preview directory. No media,
profile document, social graph, favorites/bookmarks collection, raw JSON, or
non-public record is copied into the repository. Nothing is committed, pushed,
or deployed.

## Next sprint

Implement the one-post Mastodon hot lane. It must accept one reviewed public
ActivityPub `Create`, write or update exactly one source page, touch only
bounded indexes, and prove that historical Twitter and Mastodon preview files
remain byte-identical.
