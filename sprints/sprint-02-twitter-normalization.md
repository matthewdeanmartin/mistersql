# Sprint 2: Safe Twitter Normalization and Thread Classification

## Outcome

A fail-closed, deterministic importer converts only public authored Twitter
posts from an external archive into the canonical model and correctly separates
standalone posts, tweet storms, and excluded conversation fragments.

## Scope

1. Read the ZIP in place with Python's archive APIs; never broadly extract it.
2. Locate Twitter post datasets by an explicit adapter version and allowlist.
   Unknown or changed archive shapes halt the import.
3. Stream records and retain only approved public-post fields. Exclude media
   payloads and URLs pointing to unpacked private assets.
4. Build an in-memory/on-disk ID graph containing only the minimum relationship
   fields needed for classification.
5. Publish standalone roots. Exclude replies whose complete parent chain is not
   present, replies rooted in another person's post, and protected/private
   records.
6. Classify every complete owner-authored self-reply graph rooted in an
   original tweet as one storm. Preserve parent relationships and branches;
   never flatten replies with missing or external ancestry into that graph.
7. Support a reviewed override manifest keyed by opaque source IDs for cases
   where authorial intent cannot be inferred. Overrides can include, exclude,
   split, or join; they never contain post text.
8. Emit deterministic normalized records, exclusion reason counts, a
   provenance manifest, and a dry-run report. Reports never echo private text,
   handles, email addresses, or denied dataset contents.
9. Render only synthetic end-to-end samples through the Sprint 1 templates.

## Initial classification rules

- A root authored by an approved persona and marked public is eligible as a
  standalone post.
- A reply is eligible for graph consideration only when its parent is present.
- A chain crossing to a non-owner account is excluded in full from the public
  result, except that an independently eligible owner-authored root remains a
  standalone post.
- A storm candidate follows one unbranched path of consecutive owner-authored
  self-replies. Any branch or missing link makes automatic storm inference
  stop at the last unambiguous member.
- Timing may flag candidates for review but must not alone decide that a chain
  is a storm.
- Uncertain visibility, ownership, ancestry, or schema means exclusion.

## Commands to implement

```sh
make archive-check SOURCE=twitter ARCHIVE=/absolute/external/archive.zip
make archive-schema SOURCE=twitter ARCHIVE=/absolute/external/archive.zip
make import-archive SOURCE=twitter ARCHIVE=/absolute/external/archive.zip \
  PERSONA=owner OWNER_HANDLE=owner PUBLIC_ARCHIVE=YES
make test
```

`archive-check` may report only aggregate structure. `import-archive` remains a
stub until allowlist tests are reviewed, then writes to a staging directory
that is separate from published output. Promotion is a distinct, human-reviewed
step.

## Test matrix

Use fabricated data for standalone posts, a complete three-part storm, a
missing root, a missing middle item, an external-account root, a branched
discussion containing self-replies, duplicate records, protected visibility,
unknown schema, HTML/script content, and two owner-controlled personas.

## Acceptance criteria

- Re-running an unchanged import produces byte-identical staged output.
- No raw archive file or broadly extracted archive tree appears in the repo.
- Broken/external reply chains generate no public post and no “context
  unavailable” placeholder.
- The branched discussion fixture is not flattened into a tweet storm.
- Only allowlisted public fields reach staging; denied categories are never
  deserialized beyond what is required to reject their dataset.
- Real archive text never appears in tests, logs, reports, or review artifacts.
- The owner can review counts, opaque IDs, classifications, and reasons before
  any staged record becomes publishable content.
- No Git commit, push, deployment, or PR is performed by an agent.

## Exit gate

After synthetic tests pass, the owner may run an aggregate-only archive check.
Opening real post payloads and producing staged normalized data requires a
separate explicit review of the implemented field allowlist and report format.

## Implementation checkpoint

The Twitter v1 adapter, classifier, deterministic external staging writer, and
synthetic safety suite are implemented. An aggregate-only schema inspection of
the available archive found 23,032 standard tweet records and no malformed
wrappers. A no-output dry run classified 12,041 records into 10,485 feed
objects and excluded 10,991 records, including two with location metadata.
Nothing was staged, copied into the repository, committed, or published.

Under the clarified graph rule, those feed objects are 9,307 standalone posts
and 1,178 tweet storms.

The override manifest remains available for explicit root-only or exclusion
decisions, but storm membership otherwise follows the owner-authored reply
graph rule.
