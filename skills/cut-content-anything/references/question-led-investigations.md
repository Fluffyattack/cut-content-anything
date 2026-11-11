# Deeper question-led investigations

Interpret the requested relation by meaning: actual map topology/landmarks,
internal scene references, materials, scripts, release timing and attribution.
Expand aliases and internal names from evidence. Distinguish a name, placeholder,
menu label, texture/screenshot, partial geometry and a complete playable scene.

`cutcontent search` retrieves inventory/metadata and actual supported text, with
explicit byte and result coverage. The agent performs semantic comparison and
continues through relevant unknown formats. For an unsupported single artifact,
inspect its signature and containing game folder, then develop a read-only reader
with source/docs/appropriate binary tools. Unsupported parsing is not absence.

## Common map scene

Any decoder can produce a private `cutcontent.scene.v1` JSON package:

- `schema`: `cutcontent.scene.v1`; exact scanned `build_id` and `item_id`.
- For a subscene inside an archive, `scene_name` is its actual internal name.
  Registration creates a separate gallery item linked to the source parent;
  the parent's use/release/runtime evidence does not become subscene evidence.
- `provenance`: descriptive `decoder` name/revision, `basis` explaining actual
  decoded structures and transformations, and `inputs`, a list of original
  `{path, sha256}` objects covering the files actually read.
- `scene.textures`: material objects `{name, kind, image}` with embedded PNG
  data URLs. `kind` is normally `solid`, optionally `transparent` or `liquid`.
- `scene.lightmap`: embedded PNG `image` and boolean `coloured`.
- `scene.groups`: triangle groups with material index `texture`, plus `positions`,
  `uv` and `light_uv`, each base64-encoded little-endian float32 arrays.

Positions are non-indexed triangles in right-handed Y-up coordinates: XYZ triples
and corresponding UV/light-UV pairs. Transform the source coordinate system
consistently. Use actual decoded textures. If unavailable, document a flat viewer
material/neutral light rather than inventing a game asset. Large worlds can be
exported as spatial sections. The viewer validates counts, finite values, material
references, memory limits and original-input digests. Source hashes bind inputs;
verify geometry/counts/landmarks and actual rendering to check conversion quality.
Common orbit/free-camera viewing is separate from engine collision and gameplay.

For a real built-in map round-trip:

```bash
cutcontent scene export BUILD ITEM /private/new-map.scene.json --source-file /path/to/original/game/input
cutcontent scene register BUILD ITEM /private/new-map.scene.json
cutcontent gui
```

A new decoder writes the same package directly. For a whole known map,
registration updates its preview; an archive subscene gets its own map card.
Retain converter source, source hashes
and observations privately. Never use generated geometry or screenshot mocks as
the requested real map.

## Web evidence and publication history

Always research publicly named candidates and historical/release claims. Open
official release pages, version histories and developer explanations. Verify
community leads and distinguish first-hand accounts from repetition, rumors,
fan reconstructions and mods. Record each actual page URL, date checked, build
scope and supported claim; preserve conflicts. No search hits do not establish
that content was never released.

Classify the exact scope: `asset_distribution`, `playable_release`, or
`project_release`. Distributed hidden bytes and a regular playable release can
differ. Example recording command:

```bash
cutcontent release set BUILD ITEM unreleased_candidate --scope playable_release \
  --basis "what the checked sources suggest" --source https://example.org/source-page
```

Use `unreleased_confirmed` only when checked sources establish it; confirmed
classifications require sources. `released` records a supported released scope.
`unknown` covers an unperformed check or a researched question that remains
unresolved; the visible label distinguishes recorded assessments. These fields survive rescans and are
displayed independently from local/runtime evidence. Continue relevant unresolved
checks; never convert missing evidence into a confident conclusion.
