---
name: cutcontent-reference-analysis
description: Decide whether found content is possibly unused. Trace references from game code, level scripts, entity tables, configuration and exits, report near-miss names and missing files, and state the exact coverage of the static analysis.
---

# Reference analysis: is anything using it?

"Possibly unused" is a statement about references, with a stated coverage.

## What to check

- **Game code**: string tables, script bytecode (for example QuakeC in
  `progs.dat`), compiled scripts, executable string sections, file lists the
  engine loads by itself.
- **Level data**: entity lists, spawn tables, triggers, map exits and level
  transitions. Build the exit graph from the start map and list maps without an
  incoming route.
- **Configuration**: menus, level lists, playlists, localisation tables that
  name the content.
- **Indirect names**: names built at runtime (`"level" + number`), hashed names,
  numeric file IDs. If the game uses them, string search alone cannot prove
  non-use; say so.
- **Near misses**: a reference to `slimbrn2.wav` with a stored `slmbrn2.wav`
  is a typo candidate. Missing referenced files are traces of removed content.

## How to state the result

- `possibly_unused = yes` only with the list of sources checked and their coverage.
- Name what was **not** checked (encrypted code, compressed scripts without a
  decoder, server-side data, downloadable content).
- Static absence of a route does not mean unreachable. Normal-play
  reachability is only established by an executed route
  (`cutcontent-runtime-verification`).

Record the statement on the item:
`cutcontent evidence set BUILD ITEM possibly_unused yes --basis "..." --method static`.
