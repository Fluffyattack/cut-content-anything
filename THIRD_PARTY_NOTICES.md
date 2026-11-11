# Third-party notices

This file lists every third-party component, data set and tool that this
repository includes, downloads on request, or can work together with - with
source, version, licence and how it is used. Components whose terms for
redistribution were unclear are **not** included in the repository.

## Included in this repository

### three.js 0.187.0 (MIT)

- Source: npm package `three@0.187.0` (https://github.com/mrdoob/three.js), downloaded with `npm pack`.
- Package checksum (SHA-256 of `three-0.187.0.tgz`): `ff540832ded0cfe919764d24a3d88f3e2a05f23303f876423e4f893841e90728`
- Files in `cutcontent/web/static/vendor/three/`:

  | File | Origin in the package | SHA-256 |
  | --- | --- | --- |
  | `three.module.js` | `build/three.module.js` (unchanged) | `104f56145899722094556490d787aae0617cc2fc3382f31df02d724ea1aee341` |
  | `three.core.js` | `build/three.core.js` (unchanged) | `613e370f76638fdef83926642bf256dc9615684922de1ce1f63a8583e5d78578` |
  | `OrbitControls.js` | `examples/jsm/controls/OrbitControls.js`, **modified**: the import `from 'three'` was changed to `from './three.module.js'` so the page needs no inline import map (strict Content Security Policy) | `a747d56dd959510407777f1800792b2b52c0a435980fd6e40caf303d8a674b9e` |
  | `LICENSE` | `LICENSE` (unchanged) | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |

- Licence: MIT. The full licence text is in `cutcontent/web/static/vendor/three/LICENSE`
  ("Copyright © 2010-2026 three.js authors").
- Use: drawing levels and models in the web interface.

## Not included - downloaded only when you ask for it

### LibreQuake v0.09-beta "lite" (BSD 3-Clause for art; GPL-2.0 for game code)

- Source: https://github.com/lavenderdotpet/LibreQuake/releases/download/v0.09-beta/lite.zip
- Checksum (SHA-256) verified by `cutcontent demo librequake`: `428e736b2f01d953e09a08c60bee975bdc4a0ac2219e97fa095c8af41754da83`
- Unpacked into the tool's data directory, never into this repository, never into releases or CI artefacts.
- Licences, according to the release's `docs/README-IMPORTANT-LICENCE-INFO`: models, textures and sounds
  are under the BSD 3-Clause licence (`docs/COPYING`); the QuakeC code, `progs.dat` and `gfx/pop.lmp`
  are under the GNU GPL version 2 (`docs/misc-docs/COPYING`).
- Use: local testing of the Quake adapter and the screenshots in `docs/screenshots/`.

**The screenshots in `docs/screenshots/` show LibreQuake art** (levels, a model and a texture),
which is redistributed in that rendered form under the BSD 3-Clause licence:

```
Copyright © 2019-2023
Contributors to the LibreQuake project.  All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.
  * Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in the
    documentation and/or other materials provided with the distribution.
  * Neither the name of the LibreQuake project nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS “AS
IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER
OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

LibreQuake is not affiliated with this project, and this project is not endorsed by it.

## Deliberately left out

### Qwasm (GPL-2.0) - browser port of the Quake engine

- Source: https://github.com/GMH-Code/Qwasm (checked on 2026-11-10: last change 2024-12-11, no release builds).
- Licence: GNU GPL version 2 (`gnu.txt` in that repository), as the Quake engine source it is based on.
- Why it is not bundled: there is no prebuilt release, so it would have to be built and redistributed
  from this repository, which brings GPL obligations (corresponding source, licence notices) for the
  WebAssembly binary. It stays a separately built, optional component; see
  `docs/GAME_LAUNCH.md` for the build route, browser verification and desktop alternatives.

## Optional tools that work alongside (not included)

### Optional local cartridge interpreter

The separately held private add-on used for local runtime tests contains a
source wrapper under GPL-3.0-or-later, with its complete licence text and
notices in that add-on. It links a separately obtained
[melonDS](https://github.com/melonDS-emu/melonDS) core at commit
`b86390e4428bf38ce4c1ce0e9ca446d6d25955e8`. The wrapper, builder,
compiled interpreter and upstream source are outside this public checkout.
The private builder records the source revision, build route and binary hash.

melonDS uses GPL-3.0-or-later. Its accompanying components include FreeBIOS
(BSD-2-Clause, Gilead Kutnick), Teakra (MIT, Weiyi Wang), blip-buffer
(LGPL-2.1-or-later), FatFs (its BSD-style licence) and tiny-AES (Unlicense).
Full applicable texts and pinned upstream references accompany the private
wrapper. The helper uses the core's built-in
FreeBIOS and generated firmware; no original console BIOS is bundled or downloaded.
Retain these notices and corresponding source when redistributing a built helper.

### Optional local disc interpreter

The separately held private helper used for local runtime tests uses
[PPSSPP](https://github.com/hrydgard/ppsspp) at revision
`fa50bb1976065c4f8b1b47af227d367fe9771555`. Its source patch, builder
and replay harness are outside this public checkout and carry their original
GPL-2.0-or-later notices. The linked interpreter also
contains libkirk under GPL-3.0-or-later, so the applicable conditions for a
combined binary include GPL version 3 and the other component notices.
The main scanner is a separate process and is not relicensed by this integration.

Complete GPL version 2/version 3 and LGPL-2.1 texts, original copyright notices,
29 component notices, pinned source references and their digests accompany the
private helper. The public checkout has no copy of those files.
No interpreter binary, original game, BIOS, key, save or proprietary screenshot
is distributed. The private manifest distinguishes verified archive reuse from
a fresh build of the private minimal patch; it does not claim they are identical.

| Tool | Licence | How it is used |
| --- | --- | --- |
| REA (reverse-engineering MCP server) | see its own distribution | Optional binary analysis by agents (strings, cross-references, decompilation of unencrypted executables). `cutcontent doctor` only checks whether the `rea` command exists. |
| emucap (https://github.com/mcpads/emucap) | GPL-2.0-or-later (per its README) | Optional emulator tests by agents (screenshots, inputs, memory). Not bundled, not called by this tool. |
| Playwright with Chromium | Apache-2.0 / BSD-style | Only for the optional browser acceptance run `tests/browser_acceptance.py`. Not bundled. |

## Format knowledge

All readers in `cutcontent/formats/` were written for this project from public
format descriptions and community documentation (Quake PAK/BSP/MDL/SPR/WAD and
`progs.dat`, ISO 9660, CSO, PARAM.SFO, file-table disc layouts, XDVDFS and XBE,
and cartridge headers). The id Software Quake engine
source released under the GPL served as a reference for engine *behaviour*
(search order of PAK files, light map sampling, the few file names the engine
loads by itself); no code was copied from it or from any other project. No
original boot logo, BIOS, key or other protected data is contained.

## Self-made demo data

The demo game created by `cutcontent demo create` and the test images in
`tests/fixture_builders.py` are generated by code in this repository (palette,
textures, levels, models, sounds, disc and cartridge images). They contain no
third-party data. They are project-authored; no project-wide licence has been
granted yet (see README).
## Optional local Qwasm engine

The game-start integration uses a separately built engine from
[GMH-Code/Qwasm](https://github.com/GMH-Code/Qwasm), commit
`f56b5e71e4be8effede29bae1785a5306dcc0249`. Qwasm and its Quake engine source
are under GNU GPL version 2; the upstream source contains the applicable notices.
No engine source or compiled WebAssembly binary is bundled in this repository.
`scripts/qwasm_bridge.c` is this project's small observation bridge, compiled
against the separately obtained engine headers.

The local build uses [Emscripten](https://emscripten.org/) 4.0.23 and its SDL 2
port (SDL 2.32.8, zlib licence). These tools and libraries are installed outside
the repository. Build metadata records the source revision, compiler version and
checksums. See [docs/GAME_LAUNCH.md](docs/GAME_LAUNCH.md) for the build and test steps.

If redistributing a separately built engine, retain the engine and library
licences and provide their corresponding source as required by those licences.
The gallery screenshots use LibreQuake data under the terms documented above.
