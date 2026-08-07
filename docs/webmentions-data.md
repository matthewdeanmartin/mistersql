# data/webmentions

> This file lives in `docs/` rather than in `data/webmentions/` itself: Hugo
> tries to unmarshal *everything* under `data/` as data, and a stray Markdown
> file there fails the build with
> `unmarshal of format "" is not supported`.

Written by `scripts/pull_webmentions.py`, which runs daily from
`.github/workflows/webmentions.yaml`. **Do not edit these by hand** — the next
pull will merge on top of whatever is here.

- `<slug>.json` — one file per target page. The slug comes from the page's URL
  path (`/mistersql/posts/init/` → `mistersql-posts-init`), and
  `layouts/_partials/webmentions.html` derives the *same* slug from
  `.RelPermalink` to find it. If those two rules ever disagree, mentions stop
  rendering and nothing errors — the lookup just misses.
- `_meta.json` — the high-water mark (`{"since": "..."}`), so each run asks
  webmention.io only for what arrived since the last one. Deleting it is safe:
  the next run re-fetches everything and dedupes on `wm-id`.

This directory is empty until webmention.io has collected something. That is
the normal starting state, and the site renders correctly with nothing here.

To see what the rendering looks like before any real mentions exist:

```bash
python scripts/pull_webmentions.py --fixture tests/sample-mentions.json
hugo server
# then revert: git checkout data/webmentions && rm -f data/webmentions/*.json
```
