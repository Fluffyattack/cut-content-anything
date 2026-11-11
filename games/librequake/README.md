# LibreQuake

| | |
|---|---|
| Platform and engine | PC, Quake engine (id Tech 2) |
| Builds checked | v0.09-beta Lite: `pak0.pak` SHA-256 `0dd895a425e75d9908025dcfe340f75f5b8166ada68b2d7ee54d8d91d29378ff`, `pak1.pak` SHA-256 `28423c01836341d9e3c6465b407a44ae94e4e29e954544a67739686850e39365` |
| Directory entries | [`maps/dev.bsp`](../../DIRECTORY.md#librequake-mapsdevbsp), [`sound/player/slmbrn2.wav`](../../DIRECTORY.md#librequake-soundplayerslmbrn2wav) |
| Best quality level | runtime-verified |
| Last updated | 2026-11-11 |

LibreQuake is a free game whose art is licensed under BSD 3-Clause and whose
game code is GPL. That makes it the project's public reference case: anyone can
download the same data and repeat every check.

## Summary

The release contains a developer test map, `maps/dev.bsp`, that no checked
route leads to. It was started directly in a separately built browser engine
and the player was moved. The release also contains a player sound whose name
differs by one letter from the name the game code asks for.

## Known content

### `maps/dev.bsp`

- Present in the data: **yes**. `maps/dev.bsp` inside `pak0.pak`. Both PAK
  files match the official release archive by full SHA-256.
- Possibly unused: **yes**. No exit from `start` leads to it, no literal
  game-code reference and no configuration reference. The map itself has exits
  to the first map of every episode, which fits a developer hub.
- Loaded under test conditions: **yes**. The finding card's **Open in game**
  button started the engine on `dev`; the player moved about 848 map units
  horizontally. Full measurements: [the demo](../../docs/demos/librequake-dev.md).
- Reachable in normal play: **unknown**. Bounded static analysis found no
  route; no normal route was executed.
- Release history: **released**, scope *distribution of the data*, from the
  [official v0.09-beta release](https://github.com/lavenderdotpet/LibreQuake/releases/tag/v0.09-beta).

### `sound/player/slmbrn2.wav`

- Present in the data: **yes**. `pak0.pak`, 8286 bytes.
- Possibly unused: **yes**. The name occurs in neither `progs.dat` nor
  `qwprogs.dat`, in no level entity and not in the engine's own file list.
  The game code refers to `sound/player/slimbrn2.wav`, which is missing.
- Loaded under test conditions: **unknown**. Not played in the engine yet.
- Reachable in normal play: **unknown**.
- Release history: **released**, scope *distribution of the data*.

## How the game stores content

Two PAK archives in `id1/`. Levels are BSP files with an entity lump that holds
spawn points, triggers and `trigger_changelevel` exits. Game logic is compiled
QuakeC in `progs.dat` (single player) and `qwprogs.dat` (QuakeWorld). The
built-in Quake adapter reads all of these.

## Developer functions

`maps/dev.bsp` is itself the developer function found so far: a hub with exits
to every episode start. A search for console-only commands and other test
rooms has not been written up yet.

## Research coverage

Official release page opened on 2026-11-10. No other public description of the
dev map was searched for yet.

## How to reproduce

See [docs/demos/librequake-dev.md](../../docs/demos/librequake-dev.md).

```sh
bin/cutcontent demo librequake
bin/cutcontent scan <data folder>/demo/librequake-v0.09-beta
bin/cutcontent directory match <build id>
```

## Open questions

- Play `slmbrn2.wav` in the actual engine and report the spelling difference upstream.
- Check whether newer LibreQuake releases still ship `maps/dev.bsp`.
