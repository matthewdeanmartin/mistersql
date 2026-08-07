# Webmentions on this site

How other people's likes, reposts and replies get onto these pages, and what you
have to do once by hand to make it work.

Part of the POSSE roadmap in the Mawkingbird repo
(`sprint/posse-0-overview.md`); this is sprint 1 of three. Sprints 2 and 3 are
in Mawkingbird and are about *sending* — this half is purely about receiving.

## How it fits together

```
someone likes your post on their own blog
        │
        ▼
they send a webmention ──▶ webmention.io   (a hosted receiver; it listens, we can't)
                                │
                                │  scripts/pull_webmentions.py, daily on cron
                                ▼
                          data/webmentions/*.json   (committed to this repo)
                                │
                                │  layouts/_partials/webmentions.html, at build time
                                ▼
                          rendered under the post
```

The scheduled job is the only always-on piece, and it runs on your own Actions
minutes doing something you could do by hand. Nothing here needs a server of
your own.

## One-time setup

These are the steps that are easy to get subtly wrong, so they are written out.

1. **Publish the `rel="me"` pair.** This site links to your GitHub profile
   (`params.indieauth_github` in `hugo.toml`, rendered by
   `layouts/_partials/head-additions.html`), and your GitHub profile's *Website*
   field must link back here. **Both directions are required** — IndieAuth checks
   the round trip, and one side alone silently fails to authenticate.

2. **Deploy** so those tags are actually live. Sign-in reads the published page,
   not your working copy.

3. **Sign in at <https://webmention.io>** with this site's URL. It bounces you
   through GitHub. If it refuses, step 1 has not propagated — check
   `view-source:` on the live site for `<link rel="me">` first.

4. **Copy the site identity and the API token** from webmention.io's settings.
   - Put the identity in `params.webmention_io_id` in `hugo.toml`. **Copy it
     verbatim.** For a project site served under a path
     (`…github.io/mistersql/`), the URL-encoding is fiddly, and a wrong value
     fails *silently*: mentions go to a site identity nobody owns and nothing
     ever arrives.
   - Add the token as a repository secret named `WEBMENTION_IO_TOKEN`
     (Settings → Secrets and variables → Actions). It must never be committed.

5. **Run the job once by hand** — Actions → *Pull webmentions* → *Run workflow* —
   to confirm the token works before trusting the schedule.

## The URL problem, worth deciding early

Webmentions are keyed by **URL**, and this site's posts live at
`https://matthewdeanmartin.github.io/mistersql/…`.

If you ever move to a custom domain, every mention collected against the old
URLs is stranded — the receiver has no idea the two addresses are the same page,
and migrating them is manual and lossy. **If a custom domain is coming, get it
before collecting mentions you would mind losing.** The setup above is identical
either way; only the timing matters.

## Trying it without waiting for real mentions

```bash
python scripts/pull_webmentions.py --dry-run --fixture tests/sample-mentions.json
```

Prints what it would write, needs no token. Drop `--dry-run` to actually write
the fixture data and view it with `hugo server`; then
`rm -f data/webmentions/*.json` to get back to a clean state.

The fixture deliberately contains a reply whose HTML carries a `<script>` tag
and a mention with an unrecognised property, so that two behaviours are provable:
untrusted HTML never reaches the page (the script keeps only the plain-text form,
*and* the template does not mark it safe), and unknown interaction types are
dropped rather than rendered blindly.

Running the script twice against the same input must write nothing the second
time. That is what lets the workflow skip empty commits, and therefore skip
pointless deploys.

## What renders

- **Likes and reposts** — small avatar facepiles. An author with no photo gets
  their initial.
- **Replies** — attribution plus plain text.
- **Mentions** — a plain list of links, kept separate because a bare link is not
  a stated opinion.
- **Nothing at all** when a page has no mentions. A post nobody has mentioned
  looks exactly as it did before this feature existed; there is no empty
  "0 likes" shell.
