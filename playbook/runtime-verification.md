# Runtime verification

A completed investigation starts and operates the exact build and loads every
map reported as a finding. This page explains how to make that evidence strong.

## Choose a lawful runtime

| Situation | Runtime |
| --- | --- |
| PC game with a released engine source | A source port, built and verified locally |
| PC game without source | The game's own executable in a duplicated install folder |
| Console or handheld | An emulator the owner installed, with the owner's own firmware if needed |

The gallery can start Quake-engine maps in a separately built browser engine
(`docs/GAME_LAUNCH.md`) and handheld cartridges in an optional local
interpreter (`docs/LOCAL_INTERPRETER.md`).

## Measurable assertions

Prefer values the runtime reports over screenshots that look right:

- the loaded map name;
- the player position, compared with the map's spawn point, before and after input;
- entity counts and server time advancing;
- sound: decoded sample count and non-silent samples;
- the original files' hashes, unchanged afterwards.

The LibreQuake demo records all of these: [docs/demos/librequake-dev.md](../docs/demos/librequake-dev.md).

## Test conditions versus normal play

| Route | Evidence statement |
| --- | --- |
| Direct start, console command, debug menu, changed test copy | `loaded_under_test` |
| Ordinary play from a new game without debug means | `reachable_in_normal_play` |

## Saves and state

When a test touches progress, compare saves byte by byte and say exactly which
fields changed. Do not claim full memory equality from a few compared values.

## Failure is information

If a load fails, record the error, try a second method and narrow the cause.
Keep the case open with the named blocker.
