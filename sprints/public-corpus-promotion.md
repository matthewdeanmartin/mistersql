# Public Corpus Promotion

Status: complete; Sprint 5 and Sprint 6 remain paused.

## Goal

Turn the reviewed, normalized Twitter and Mastodon posts into the only real
social data that may be tracked and supplied to Hugo, without copying raw
archives or checking in generated HTML.

## Delivered

- A strict top-level and nested-field publication allowlist.
- Sanitized inert HTML and HTTP(S)-only URL validation.
- Public/unlisted visibility enforcement and media exclusion.
- Deterministic source/year JSON shards with an aggregate hash manifest.
- A safety sentinel, unexpected-file checks, duplicate checks, and stable sort
  checks.
- A Hugo content adapter that reads bulk shards from `assets/` and creates
  normal pages, storms, tags, pagination, RSS, and permalinks.
- Local `make promote-public-corpus` and `make validate-public-corpus` targets.
- The same validation gate in GitHub Actions before Hugo builds.
- Synthetic privacy, active-HTML, unknown-field, and determinism tests.

## Baseline

- 10,485 Twitter feed objects.
- 4,800 Mastodon feed objects.
- 15,285 total canonical records in 24 shards.
- 0 changes on an immediate repeat promotion.
- 16,141 Hugo pages and 396 paginator pages.
- Approximately 79 seconds for a production render-to-memory build locally.

## Operator boundary

No agent stages, commits, pushes, deploys, or opens a pull request. The operator
reviews the complete change set and chooses whether to publish. The two raw ZIP
archives remain outside the repository and must never be added.
