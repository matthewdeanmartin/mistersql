# Sprint 1: Static Social Shell and Safety Contracts

## Outcome

A first-party Hugo shell renders existing and synthetic content in the mock's
three-column social style, remains complete without JavaScript, and establishes
the contracts future importers must obey.

## Scope

1. Replace Ananke presentation through project-local layouts and assets; do not
   edit the theme submodule.
2. Reuse the mock's visual tokens: pale/dim backgrounds, white center column,
   600 px feed, subtle borders, blue accent, compact metadata, rounded avatars,
   responsive rails, and sticky header.
3. Implement semantic regions: skip link, header/nav, left profile/tag rail,
   main feed, and right archive/widget rail.
4. Render existing Hugo posts as social cards and single pages as expanded
   cards. Use plain links and server-rendered pagination.
5. Configure and render Hugo `tags` taxonomy as the blog hashtag system.
6. Define the normalized post/storm schema and synthetic fixtures. A storm is a
   single feed object with ordered parts, while a discussion remains a post
   with separately modeled replies.
7. Add automated checks for no-JS content presence, keyboard landmarks,
   overflow at mobile widths, and absence of remote runtime dependencies.
8. Add leak checks that reject archive-like files, denied dataset names,
   unexpectedly large new files, and generated output containing fixture
   canaries.

## Explicitly out of scope

- Reading or importing the real Twitter archive.
- Media extraction or publication.
- Mastodon import, persona switching, client-side search, likes, posting,
  account login, or any live social-server call.
- Committing, pushing, deploying, or opening a pull request.

## Proposed files

- `layouts/baseof.html`
- `layouts/home.html`, `layouts/list.html`, `layouts/single.html`
- `layouts/_partials/social/{header,left-rail,right-rail,card,storm}.html`
- `assets/css/social.css`
- `data/site-profile.*` for public, reviewed profile copy
- `docs/content-schema.md`
- `tests/fixtures/` containing synthetic records only
- `scripts/check_public_tree.py`

## Acceptance criteria

- Home, tag, list, and single pages contain readable posts and navigation when
  JavaScript is blocked.
- Desktop layout has three columns; narrow layouts collapse rails without
  hiding the feed or creating horizontal scrolling.
- Header and rails contain no controls that imply a working social client.
- The left rail contains static owner/blog information and Hugo tag links.
- Long posts and storms use the same coherent card language.
- No essential asset or content is fetched from a social server at runtime.
- Safety tests use only obviously fictional synthetic data.
- `make build` and `make test` pass in Git Bash using `uv run` for Python.

## Review gate

The owner reviews screenshots at desktop, tablet, and mobile widths plus a
render with JavaScript disabled. Importer implementation does not begin until
the schema, storm appearance, and privacy allowlist are approved.

