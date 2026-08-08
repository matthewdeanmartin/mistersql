# Public Corpus Publication Runbook

Run every command from Git Bash. Python is always invoked as `uv run` through
the Makefile. Never extract either raw ZIP and never place one inside this
repository.

## What is safe to check in

The publication boundary is `assets/public_archive/` only. It contains an
exact safety sentinel, an aggregate manifest, and deterministic JSON shards
grouped by source and year.

Each record is copied through a strict allowlist. Import provenance, archive
paths, exclusions, contact data, direct messages, location metadata, media,
unknown fields, active HTML, and non-public visibility cannot enter this
directory. Hugo creates final static pages from these shards at build time;
15,000 generated HTML source files are not checked in.

Do not add either archive ZIP, `content/posts/imported/`, `var/`, or an external
staging directory. Agents and automation never stage, commit, push, or deploy.

## Promote both reviewed archives

```sh
make promote-public-corpus \
  TWITTER_ARCHIVE=/absolute/path/outside/mistersql/twitter-archive.zip \
  MASTODON_ARCHIVE=/absolute/path/outside/mistersql/mastodon-archive.zip \
  PERSONA=mistersql \
  OWNER_HANDLE=mistersql \
  PUBLIC_ARCHIVE=YES \
  OWNER_CONTROLLED=YES
```

The confirmations are deliberate. Twitter's export does not provide reliable
per-record historical visibility, while Mastodon records are admitted only
when their ActivityPub audience is public or unlisted. The command reports
aggregate counts and hashes only.

Re-run the same command immediately. A deterministic result reports
`changed: 0`. Any change must be understood before publication.

## Validate and build

```sh
make validate-public-corpus
make test
make build
```

Validation rechecks every field, HTML fragment, URL, visibility, shard
identity, sort order, duplicate identity, unexpected file, and manifest hash.
It also fails if Git tracks a ZIP/tar archive or ignores the public manifest.
The same validator runs in GitHub Actions before Hugo.

The August 2026 baseline contains 15,285 canonical records in 24 shards and
builds 16,141 Hugo pages plus 396 paginator pages in about 79 seconds on the
local Windows machine. This is within the 120-second workflow target. The
checked-in source corpus is approximately 17 MB; generated `public/` HTML is a
build artifact, not the canonical data.

## Human review before committing

Review `git status --short`, the code diff, the manifest, shard names, and
aggregate sizes. Confirm that `git ls-files '*.zip' '*.tgz' '*.tar.gz'` is
empty. Then the operator—not an agent—may choose what to stage and commit.

Periodic full-archive refreshes use the same promotion command. The future
single-post Mastodon path remains paused and will use a bounded incremental
lane rather than rewriting the historical corpus.
