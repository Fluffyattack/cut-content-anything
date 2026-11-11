# Reference analysis: is it used?

"Possibly unused" means: nothing in the checked sources refers to it. The
statement is only as good as its coverage, so the coverage is part of it.

## Sources of references

| Source | Examples | Notes |
| --- | --- | --- |
| Game code | QuakeC `progs.dat`, script bytecode, executable string tables | Names can be built at runtime; look for format strings such as `e%dm%d` |
| Level data | Entities, spawn tables, triggers, exits | Build the exit graph from the start map |
| Configuration | Menu definitions, level lists, playlists | Often plain text or simple tables |
| Localisation | Text tables naming items, levels, characters | A name with text but no asset is a trace too |
| Engine | Files the engine loads on its own (fonts, palettes, default sounds) | The Quake adapter lists them explicitly |

## Exit graphs

Collect every level transition (for Quake, `trigger_changelevel` targets) and
walk from the start map. Maps without an incoming edge are candidates. A map
can still be reached by console command, a menu or a save game; say which of
these were checked.

## Near-miss names and missing files

Compare referenced names with stored names by edit distance. A reference to a
missing file with a stored near-twin is a strong hint of a typo that leaves the
stored file unused. A reference to a missing file without a twin is a trace of
removed or not-yet-added content; record it as its own finding.

## Wording

Good: "No reference in progs.dat, qwprogs.dat, level entities or the engine's
file list (all decoded; nothing encrypted)."
Not acceptable: "Unused." without coverage.
