# Canonical Social Post Schema

The importer must normalize every source into this small public model before
anything reaches Hugo or the frozen historical renderer. Fields not listed here
are denied by default.

## Common fields

| Field | Required | Purpose |
| --- | --- | --- |
| `schemaVersion` | yes | Version of this normalized contract. |
| `socialKind` | yes | `post` or `storm`; replies are not a publishable top-level kind. |
| `source` | yes | `twitter` or `mastodon`. |
| `persona` | yes | Reviewed owner-controlled persona key. |
| `sourceId` | yes | Stable source identifier used for idempotency. |
| `date` | yes | Original public publication timestamp. |
| `canonicalUrl` | no | Original public URL when it is safe and still meaningful. |
| `language` | no | Public source language code. |
| `contentHtml` | yes | Sanitized, allowlisted post markup. |
| `contentText` | yes | Plain-text equivalent for indexing and auditing. |
| `tags` | no | Public hashtags, normalized for Hugo's `tags` taxonomy. |
| `contentWarning` | no | Public source content warning. |
| `visibility` | no | Explicit public or unlisted Mastodon visibility. |
| `metrics` | no | Archived public like and repost/boost totals. |
| `poll` | no | Read-only Mastodon poll options and archived vote totals. |
| `import` | yes | Adapter version, import time, and non-secret source checksum. |

Media is not part of the current schema. Location, contacts, direct messages,
email addresses from account data, advertising data, IP data, and source archive
paths are never valid fields.

Mastodon `Note` and `Question` objects are accepted only when the ActivityPub
Public audience appears in `to` or `cc`. Public-in-`to` records normalize as
`public`; Public-in-`cc` records normalize as `unlisted`. Followers-only,
direct, and otherwise non-public objects are denied.

## Storm fields

A storm adds `parts`, a parent-before-child graph whose entries contain their
own source ID, parent ID, depth, timestamp, sanitized HTML/text, and tags. If a
public root tweet has one or more complete owner-authored self-replies, the
entire available self-reply graph is one storm, including branches. Replies
with missing or external ancestry never become storm parts.

## Relationship workspace

Reply IDs may be held temporarily during classification, but they are not
automatically publishable content. A reply is discarded if any ancestor is
missing, if the chain is rooted in another person's post, or if ownership or
visibility is uncertain. A reviewed override file may refer to opaque source
IDs and classification actions, but may not contain post text.

## Hugo projection

Hot-lane records map the common fields to Hugo front matter. The body contains
only sanitized public content. Cold-lane HTML uses the same schema and template
contract so URLs and appearance do not depend on which lane rendered a post.
