---
name: cutcontent-runtime-verification
description: Start and operate the exact local game build in a real engine or emulator, load every map reported as a finding, verify image, input and sound, and record runtime evidence with screenshots. Separates test loading from normal-play reachability.
---

# Runtime verification: the game itself, not a preview

Every completed investigation starts and operates the exact build. A 3D
preview, a scan, a mock or a synthetic fixture is never a game start.

## Prepare

- Use a lawful runtime: the game's own executable, a source port or an
  emulator the owner installed. Never download games, BIOS, firmware or keys.
  If a lawful component is missing, ask whether the owner can supply their own copy.
- Work on an isolated copy when a test needs a change (for example a
  configuration that starts a specific map). Record the exact change. The
  original stays read-only; compare its hash before and after.

## Execute and observe

1. Start the game and confirm the build identity on screen or in logs.
2. Operate it: real input, image changes that follow the input, sound output
   where available.
3. Load **every map reported as a finding**. Prefer a measurable assertion
   (map name reported by the engine, player position, entity count) over a
   screenshot that "looks right".
4. Keep screenshots and a short observation log. Proprietary captures stay private.

## Record

```sh
cutcontent evidence set BUILD ITEM loaded_under_test yes \
  --basis "what was executed and what was observed" --method runtime --access-route direct_start
```

`reachable_in_normal_play` is set only after a normal route without debug
means was actually played. A direct start or a debug-menu load is a test
condition.

## When it fails

Do not stop at the first failure. Try a second suitable method (another
runtime, another load route, logs, memory inspection), narrow down the cause
and keep the case open with the specific blocker. Say which checks did not run.
