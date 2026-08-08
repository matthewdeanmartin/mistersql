# Sprint 3: Hugo Preview Compilation and Scale Baseline

## Outcome

`make serve` displays the real normalized Twitter archive as social cards and
graph-shaped tweet storms without making any imported content trackable or
publishable.

## Implemented

- The storm classifier treats any complete owner-authored self-reply graph
  rooted in an original tweet as one storm, including branches.
- Every storm part retains its parent ID and graph depth. Hugo renders the
  parts inside one connected social card.
- `make preview-archive` compiles canonical records into deterministic Hugo
  HTML content files under `content/posts/imported/`.
- The preview directory is Git-ignored, sentinel-protected, and contains only
  drafts. Production Hugo builds exclude it; `make serve --buildDrafts` shows
  it.
- The compiler compares bytes and writes only changed pages. It can safely
  remove stale generated pages only beneath the sentinel-protected directory.
- Hashtags populate Hugo's taxonomy pages and left rail.
- Twitter URL entities are expanded while importing. Missing destinations are
  resolved once into an ignored local cache, then baked into the preview so
  rendered pages do not depend on `t.co`.
- Archive favorite and retweet totals appear on roots and individual storm
  parts.
- Twitter transport entities are decoded once before safe HTML rendering,
  avoiding the earlier double-escaping.

## Real archive baseline

- Source tweets: 23,032
- Hugo feed objects: 10,485
- Total site posts with the two hand-written examples: 10,487
- First preview compile: approximately 14 seconds
- No-change normalization/compile pass: approximately 4 seconds
- Cold Hugo render of all drafts: approximately 48 seconds on this workstation
- Home page: 40 server-rendered cards with 263 static pagination pages
- Development serving uses Hugo's in-memory renderer, so preview output does
  not leave stale pages in `public/`

The 48-second Hugo baseline is acceptable for reviewing a bulk theme change,
but not for one-at-a-time Mastodon ingestion. It validates the planned cold/hot
split: historical Twitter HTML should be frozen, while a bounded recent window
remains in Hugo's hot content graph.

## Safety status

No raw archive, media, account data, contacts, DMs, or generated preview page is
tracked by Git. No imported page is eligible for a production build. Nothing
was committed, pushed, or deployed.

## Remaining cold-lane work

1. Choose a stable historical cutoff and URL manifest.
2. Render historical pages, pagination, year pages, and tag shards into a
   reviewable static artifact.
3. Keep only a bounded recent window in Hugo content.
4. Merge cold counts/latest-card metadata into the hot shell without asking
   Hugo to load every historical source page.
5. Prove that adding one Mastodon post leaves cold files byte-identical and
   completes inside the agreed build budget.
