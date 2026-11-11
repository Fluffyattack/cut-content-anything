# Directory of documented hidden and cut content

<!-- Generated from data/directory.json by `cutcontent directory build`. Do not edit by hand. -->

3 entries for 2 games. Every entry keeps four evidence statements, the release history and its quality level separate. Schema and rules: [data/SCHEMA.md](data/SCHEMA.md).

Quality levels:

- **source-reports**: A public source was opened and states it; not yet checked in actual data.
- **data-verified**: The actual bytes or code were located in an identified build.
- **runtime-verified**: Loaded and observed in the actual game, engine or emulator for an identified build.

Evidence columns: **D** present in the data · **U** possibly unused · **T** loaded under test conditions · **N** reachable in normal play.

| Game | Content | Kind | Platform | D | U | T | N | Release | Quality | Checked |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| LibreQuake | `maps/dev.bsp` ([write-up](games/librequake/README.md)) | map | PC | yes | yes | yes | unknown | released (asset_distribution) | **runtime-verified** | 2026-11-10 |
| LibreQuake | `sound/player/slmbrn2.wav` ([write-up](games/librequake/README.md)) | audio | PC | yes | yes | unknown | unknown | released (asset_distribution) | **data-verified** | 2026-11-11 |
| Quake (1996) | `monster_ogre_marksman` | enemy | PC | unknown | unknown | unknown | unknown | unknown | **source-reports** | 2026-11-11 |

## Details

### LibreQuake: `maps/dev.bsp`

A developer test map shipped inside pak0.pak of the v0.09-beta Lite release. No exit, game-code reference or configuration in the checked data leads to it; it starts directly in the engine.

- Present in the data: **yes** — Stored as maps/dev.bsp in pak0.pak; the PAK matches the official release ZIP by full SHA-256.
- Possibly unused: **yes** — No route in the checked exit graph from 'start', no literal game-code reference and no configuration reference (bounded static analysis).
- Loaded under test conditions: **yes** — Started directly on 'dev' in a separately built browser engine; actual horizontal player movement of about 848 map units was observed.
- Reachable in normal play: **unknown**
- Release: **Release supported by sources**, scope: Distribution of the data — Included in the official v0.09-beta Lite release archive; a regular playable route was not established.
- Checked build: v0.09-beta Lite, pak0.pak (`sha256:0dd895a425e75d9908025dcfe340f75f5b8166ada68b2d7ee54d8d91d29378ff`)
- Notes: Free data (BSD 3-Clause art, GPL game code), so this case is published as the project's reference demo.
- Sources: <https://github.com/lavenderdotpet/LibreQuake/releases/tag/v0.09-beta>

### LibreQuake: `sound/player/slmbrn2.wav`

A player sound stored in pak0.pak that nothing references. The game code asks for the almost identical name sound/player/slimbrn2.wav, which is missing from the data, so a spelling difference probably leaves this sound unused.

- Present in the data: **yes** — Stored as sound/player/slmbrn2.wav in pak0.pak (8286 bytes).
- Possibly unused: **yes** — The name does not occur in progs.dat, qwprogs.dat, any level entity or the engine's own file list; game code references the missing sound/player/slimbrn2.wav instead.
- Loaded under test conditions: **unknown**
- Reachable in normal play: **unknown**
- Release: **Release supported by sources**, scope: Distribution of the data — Included in the official v0.09-beta Lite release archive.
- Checked build: v0.09-beta Lite, pak0.pak (`sha256:0dd895a425e75d9908025dcfe340f75f5b8166ada68b2d7ee54d8d91d29378ff`)
- Notes: Next step: play the sound in the actual engine (for example through a test map that triggers it) and check whether the game code's misspelled name is a typo upstream.
- Sources: <https://github.com/lavenderdotpet/LibreQuake/releases/tag/v0.09-beta>

### Quake: `monster_ogre_marksman`

A spawn function for an 'Ogre Marksman' enemy. In the game code that id Software published under the GPL, it only calls the normal Ogre's spawn function, so a level placing it gets an ordinary Ogre.

- Present in the data: **unknown** — Not yet checked in a shipped progs.dat; the published source file quakec/monsters/ogre.qc defines it.
- Possibly unused: **unknown**
- Loaded under test conditions: **unknown**
- Reachable in normal play: **unknown**
- Release: **Release history not checked**
- Notes: Open work: identify an owned 1996 build, confirm the function in its progs.dat, check every shipped level's entities for the class name, and spawn it in the actual engine. The published source is the later re-release QuakeC, so compare it with the original build before relying on it.
- Sources: <https://github.com/id-Software/quake-rerelease-qc/blob/main/quakec/monsters/ogre.qc>
