# Archive Import Runbook

Run every command from Git Bash. Python is always invoked by the Makefile as
`uv run`; do not activate a virtual environment.

## Safety boundary

- Keep the raw archive outside this repository.
- Do not extract the ZIP.
- Use only an archive belonging to an owner-controlled persona.
- Set `PUBLIC_ARCHIVE=YES` only after confirming that persona's archived posts
  are eligible for public display. Twitter archives do not carry reliable
  historical visibility information, so the importer cannot infer this.
- A real staging directory must also be outside the repository and must not
  already exist.
- Dry runs print aggregate counts only. They do not print tweet text, handles,
  member paths, contact data, or raw excluded identifiers.

## Structural checks

```sh
make archive-check \
  SOURCE=twitter \
  ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip

make archive-schema \
  SOURCE=twitter \
  ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip
```

The first command reads only the ZIP directory. The second opens only the
Twitter `tweets.js` dataset and reports record shape and field names, never
field values. Unknown fields stop normalization until the allowlist is
reviewed.

## Twitter dry run

```sh
make import-archive \
  SOURCE=twitter \
  ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip \
  PERSONA=mistersql \
  OWNER_HANDLE=mistersql \
  PUBLIC_ARCHIVE=YES
```

The result reports included records, feed objects by kind, and exclusions by
reason. It writes nothing. A high missing/external ancestor count is expected:
those records are deliberately absent from the public result.

## Mastodon bulk import

Mastodon exports carry record-level ActivityPub audience information, so the
adapter does not need Twitter's blanket public-archive assumption. Confirm only
that the archive belongs to an owner-controlled persona:

```sh
make archive-schema \
  SOURCE=mastodon \
  ARCHIVE=/absolute/path/outside/mistersql/mastodon-archive.zip

make import-archive \
  SOURCE=mastodon \
  ARCHIVE=/absolute/path/outside/mistersql/mastodon-archive.zip \
  PERSONA=mistersql \
  OWNER_CONTROLLED=YES
```

The importer reads only `outbox.json`. It accepts `Create` activities whose
`Note` or `Question` has the ActivityPub Public audience in `to` or `cc`.
Followers-only/direct posts, boosts, empty posts, incomplete external
conversations, and descendants of excluded conversations are denied. Content
warnings, hashtags, polls, language, timestamps, canonical URLs, and archived
engagement counts are preserved. Attachments are counted but neither opened
nor copied.

## Reviewed overrides

An optional JSON file can classify an eligible root without including its text:

```json
{
  "version": 1,
  "roots": {
    "123456789012345678": "storm",
    "223456789012345678": "post",
    "323456789012345678": "exclude"
  }
}
```

Pass it as `OVERRIDES=/path/to/reviewed-overrides.json`. Unknown or
already-excluded IDs fail closed.

## External staging

Only after reviewing the dry-run counts:

```sh
make stage-archive \
  SOURCE=twitter \
  ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip \
  PERSONA=mistersql \
  OWNER_HANDLE=mistersql \
  PUBLIC_ARCHIVE=YES \
  STAGING=/absolute/new/path/outside/mistersql/twitter-staging
```

Staging contains deterministic normalized JSON records, an aggregate report,
and exclusions keyed by hashed opaque IDs. It is not published content. Human
review and a separate future promotion command are required before any record
enters Hugo or frozen historical HTML.

## Link expansion and legacy local preview

Twitter's archive usually includes the final destination for `t.co` links. The
importer bakes those destinations into generated content. For short links whose
destination is absent from the archive, resolve them once into a local ignored
cache before compiling the preview:

```sh
make resolve-links \
  SOURCE=twitter \
  ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip \
  PERSONA=mistersql \
  OWNER_HANDLE=mistersql \
  PUBLIC_ARCHIVE=YES
```

The resulting `var/twitter-link-cache.json` is private local build state and is
ignored by Git. Rendered pages contain destination URLs directly, so readers do
not depend on Twitter's redirect service.

The legacy preview command can still compile quarantined drafts for importer
diagnostics:

```sh
make preview-archive \
  SOURCE=mastodon \
  ARCHIVE=/absolute/path/outside/mistersql/mastodon-archive.zip \
  PERSONA=mistersql \
  OWNER_CONTROLLED=YES

```

The compiler writes only to `content/posts/imported/`. That directory is
ignored by Git, carries a safety sentinel, and every page has both `draft: true`
and `privatePreview: true`. Hugo now ignores this directory entirely because
the tracked public corpus supersedes it; `make serve` shows only validated
public records. The ignored drafts may be retained locally for diagnostics,
but they are neither build inputs nor files to check in.

Re-running `preview-archive` rewrites only changed records and removes stale
generated pages for that source. A Mastodon refresh cannot delete or rewrite
Twitter preview pages, and vice versa. It refuses to operate if the target
lacks its exact sentinel.

For the reviewed publication workflow, see `docs/publication.md`.
