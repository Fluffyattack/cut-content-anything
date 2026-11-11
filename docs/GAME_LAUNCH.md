# "Open in game" - starting a level in a real engine

The gallery can open the selected level in a separately built **Qwasm** engine.
The button stays disabled until that exact engine build passes the browser test.

"Explore in 3D" is a viewer: a free camera that flies through the level's real
geometry, textures and light maps, with an optional collision-based walk mode.
The viewer does not execute game code. "Open in game" starts the real engine,
including game code, monsters and items.

## Engine build

The integration uses Qwasm commit `f56b5e71e4be8effede29bae1785a5306dcc0249`
with Emscripten 4.0.23, SDL 2.32.8 and software rendering at 640 × 480.
The small bridge in `scripts/qwasm_bridge.c` reads the actual engine map,
player position and server time for the acceptance test.
Engine source and binaries stay outside this repository; their sources and
licences are listed in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Install and verify

1. Install the [Emscripten SDK](https://emscripten.org/docs/getting_started/downloads.html)
   outside this checkout, then activate version 4.0.23:

   ```sh
   /path/to/emsdk/emsdk install 4.0.23
   /path/to/emsdk/emsdk activate 4.0.23
   . /path/to/emsdk/emsdk_env.sh
   ```

2. Obtain the pinned Qwasm source, also outside the checkout:

   ```sh
   git clone https://github.com/GMH-Code/Qwasm /path/to/Qwasm
   git -C /path/to/Qwasm checkout f56b5e71e4be8effede29bae1785a5306dcc0249
   ```

3. From the Cut Content Anything checkout, build the engine:

   ```sh
   python3 scripts/build_qwasm.py --source /path/to/Qwasm
   bin/cutcontent demo librequake
   ```

   The default output is the application's data directory under `engines/qwasm/`.
   To use another location, pass `--output /path/to/engine` and set
   `CUT_CONTENT_QWASM_DIR=/path/to/engine` when testing and starting the gallery.
   No game files are embedded in this build. Compilation uses one worker to
   keep small machines responsive.

4. Install Playwright and Chromium in a Python environment, then test:

   ```sh
   python3 -m venv .venv
   . .venv/bin/activate
   python3 -m pip install playwright
   python3 -m playwright install chromium
   python3 tests/browser_game_acceptance.py --record-verification --screenshots test-output/game
   bin/cutcontent doctor
   bin/cutcontent gui
   ```

   The test opens LibreQuake's `lq_e0m1` and `dev` through the gallery, checks the
   actual engine state, moves the player, and compares game-file checksums before
   and after. It writes `browser-verification.json` only after all checks pass.
   Changing the JavaScript or WebAssembly binary invalidates that verification.

## Playing and limits

Open a level and click **Open in game**. Click inside the game to capture
the mouse; use **W A S D**, **Space** to jump, and **Ctrl** or the mouse to fire.
**Esc** opens the engine menu. **Explore in 3D** returns to the preview and stops
the engine. Closing the viewer also stops it.

The server reads only this game's files in allowed folders. A session address
expires after four hours. PAKs are streamed to the browser and loaded into its
virtual file system; game saves and settings stay in browser storage. Original
game files are never written. The browser limit is 512 MiB and 4096 source files.

This integration targets the original Quake formats. Extended engine features,
large modern mods and console emulators are outside this engine's scope. The
self-made preview demo lacks complete engine resources, so it keeps its game
button disabled with a reason. Other games may need a different engine; an
engine error is shown with its messages.

Loading a level directly is a test under test conditions. It does not prove
that the level is reachable in normal play. Record observations with
`cutcontent evidence set <build-id> <item-id> loaded_under_test yes --basis "..." --method runtime --access-route direct_start`.

The [fresh finding-card demo](demos/librequake-dev.md) records a complete actual
run from the `dev` card to its spawn and horizontal player movement. Its UI
keeps distribution, direct start and the bounded search for regular access
separate.

## Alternative that works today

Any desktop Quake engine can open a level directly. With the LibreQuake data
from `cutcontent demo librequake` (folder shown by `cutcontent list`):

```sh
# examples - use the engine you have installed
ironwail -basedir <folder that contains id1> +map lq_e0m1
quakespasm -basedir <folder that contains id1> +map dev
fteqw -basedir <folder that contains id1> +map lq_e0m3
```

The level name is the file name in `maps/` without `.bsp`. Starting a level for
which no access was found in the checked references (such as LibreQuake's `dev`)
this way is a test under test
conditions: record what you saw with
`cutcontent evidence set <build-id> <item-id> loaded_under_test yes --basis "..." --method runtime --access-route direct_start`.
