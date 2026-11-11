---
name: cutcontent-release-history
description: Establish the publication history of a finding with checked sources - whether it was shipped in data, regularly playable, or never released - with scope, date and URLs. Prevents unreleased claims based on names, debug menus or empty searches.
---

# Release history: a separate question with its own evidence

Whether content was released is independent of whether it is used. A hidden
map can ship inside a released game without ever being regularly playable.

## Scope

- `asset_distribution`: the bytes were distributed in a release.
- `playable_release`: players could reach it in a regular released version.
- `project_release`: the game or project itself was released.

## Status

- `released`: checked sources (or the release archive itself) support release in the scope.
- `unreleased_candidate`: sources suggest it, but do not establish it.
- `unreleased_confirmed`: checked sources establish that it was not released in the scope.
- `unknown`: not checked, or checked without a result.

Names such as `beta`, `test`, `proto`, a debug menu or an absent reference are
never enough for an unreleased claim. Check other regions, revisions, patches,
demos, ports and downloadable content before saying a scope never had it.

## Record

```sh
cutcontent release set BUILD ITEM released --scope asset_distribution \
  --basis "the official release archive contains the same file by SHA-256" \
  --source https://example.org/official-release-page
```

Keep the URLs, the check date and conflicting sources. These records survive rescans.
