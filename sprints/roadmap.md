# MisterSQL Social Archive Roadmap

## Product contract

MisterSQL is a read-only POSSE archive whose source material comes from the
owner's Twitter/X and Mastodon accounts. It should feel like the three-column
Angular social UI in `../mastodon_mock/ui`, but every published page is static,
semantic HTML and remains navigable with JavaScript disabled. JavaScript may
enhance the experience; it may not supply posts, navigation, pagination,
content warnings, or essential metadata.

The archive is intentionally about the owner's public writing. It is not a
reconstruction of Twitter or Mastodon conversations and is not a social-media
client.

## Non-negotiable privacy contract

Raw archives stay outside the repository. The importer reads an explicitly
provided external path and writes a new, allowlisted representation. It never
copies or broadly extracts the archive. The following classes are always
denied: contacts/address books, direct messages, private or protected posts,
drafts, ad data, account-security records, location/IP history, and unknown
datasets. Media is denied until a later sprint defines a separate policy.

Diagnostics identify rejected records with opaque source IDs and reason codes;
they do not echo text, handles, email addresses, paths within the archive, or
payload fragments. Real archive data is never used as a test fixture.

Agents and automation do not commit, push, deploy, or open pull requests. The
owner performs those actions after reviewing the complete diff for leaks.

## Information architecture

The desktop shell keeps the mock's three columns:

- Left: a static owner/blog profile card, Hugo-generated tag list, and later
  blog-relevant widgets.
- Center: chronological social-post cards, unified tweet-storm cards, taxonomy
  listings, and single-post pages.
- Right: archive navigation, source/year filters, archive statistics, and other
  static widgets. It has no ads or server status.
- Header: the mock's visual language with only applicable blog navigation.
  Account switching is deferred but the layout leaves room for future persona
  switching among imported owner-controlled accounts.

Hugo supports hashtags through its built-in taxonomy system. Imported hashtags
will populate the `tags` front-matter field and render as static term pages.

All normal posts use the social card language, including long posts. A single
page may give long text more room, but it does not switch to an unrelated essay
theme.

## Canonical content model

Every accepted source post is normalized before rendering. The model contains
only explicitly public fields such as source, persona ID, source post ID,
canonical URL, public timestamp, sanitized body HTML/plain text, language,
public hashtags, content warning, reply identifiers needed for classification,
and import provenance. Media fields are excluded for now.

Rendered objects have distinct kinds:

- `post`: a public standalone Twitter or Mastodon post.
- `storm`: a complete owner-authored reply graph rooted in an original tweet.
  If the owner replies to that root or its owner-authored descendants, the
  whole available graph is one feed object, including branches.
- `reply`: not published unless the complete ancestor chain is present and the
  conversation policy explicitly admits it. No "context unavailable" cards
  are generated.

A post with a discussion beneath it is not automatically a storm. Branches,
gaps, replies to another account, and ambiguous self-replies default to
exclusion or standalone-root treatment. Because intent cannot always be
recovered from archive data, a reviewed override manifest will allow an opaque
source ID to be classified as a storm root, standalone post, or excluded
record. The manifest contains no post text.

## Performance architecture

Reviewed bulk archives are stored as deterministic source/year JSON shards
under `assets/public_archive/`. Hugo content adapters project those records
into its normal page graph, preserving one layout contract, stable permalinks,
pagination, the home RSS feed, and tag taxonomy pages. Generated HTML remains a
build artifact instead of a second tracked source of truth.

The August 2026 baseline of 15,285 records builds in about 79 seconds locally,
inside the 120-second workflow target. Global and rail partials are cached,
only the home feed is paginated, and only the home RSS feed is emitted.

The future hot lane for one-at-a-time Mastodon ingestion remains distinct. It
must touch bounded canonical shards and indexes without rewriting historical
records; Sprint 5 is paused until that contract is resumed.

## Delivery sequence

### Sprint 1 — Static social shell and contracts

Create first-party Hugo layouts and CSS that adapt the mock's three-column
design, establish semantic/no-JS rendering, define the canonical schema and
golden synthetic examples, and add privacy/build guardrails.

### Sprint 2 — Safe Twitter normalization and thread classification

Implement a streaming ZIP reader for allowlisted Twitter datasets, normalize
public authored posts without media, classify complete self-authored storms,
exclude broken/external reply chains, and render a synthetic end-to-end sample.

### Sprint 3 — Bulk renderer and scale benchmark

Benchmark Hugo-only, frozen-static, and hybrid builds with at least 20,000
synthetic records. Implement deterministic cold rendering, sharded indexes,
incremental invalidation, and reproducibility manifests.

### Sprint 4 — Mastodon archive import

Normalize Mastodon archive exports into the same canonical model, including
content warnings and public visibility rules. Add idempotent periodic imports
without changing unrelated historical output.

### Sprint 5 — One-post Mastodon ingestion

Add the bounded hot-lane entry point for one exported/public post at a time.
Update only the post, affected tag/year/persona indexes, feeds, and manifest;
measure and enforce a short build budget.

### Public corpus promotion — completed before Sprint 5

Promote the reviewed Twitter and Mastodon archives through a second strict
publication allowlist into tracked deterministic shards. Validate every field,
HTML fragment, URL, visibility, duplicate identity, sort order, unexpected
file, and manifest hash in local builds and CI. Raw ZIPs and generated HTML are
not tracked. Sprint 5 and Sprint 6 remain on hold.

### Sprint 6 — Persona navigation and archive discovery

Add static persona pages and optionally repurpose the header account control as
a persona filter/switcher. Add source/year/tag navigation and a no-JS search or
index fallback before considering client-side search enhancement.

### Deferred — Media

Inventory size and formats using aggregate-only tooling; decide storage,
copyright, sensitive-content, alt-text, deduplication, thumbnail, and bandwidth
policies before any real media is copied or published.

## Definition of done for the program

- The site closely reflects the mock's three-column visual language.
- Essential content and navigation work with JavaScript disabled.
- Bulk and one-post imports are deterministic, idempotent, and bounded.
- Complete tweet storms are unified; ambiguous or broken conversations do not
  become misleading fragments.
- No denied archive category or raw archive material enters Git or published
  output.
- Adding one Mastodon post does not rebuild or rewrite the historical corpus.
