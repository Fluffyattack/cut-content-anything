# How Cut Content Anything is built

```
                ┌──────────────── cutcontent (CLI) ───────────────┐
 you / agent ──►│ doctor · scan · report · list · evidence · task │
                └───────────────┬─────────────────────────────────┘
                                │ same functions
                ┌───────────────▼───────────────┐      ┌────────────────────────┐
 browser ──────►│ web/server.py (127.0.0.1 only) │─────►│ core/service.py         │
  (gallery,     │ token, host check, folders     │      │ discovery, scan, preview│
   3D viewers)  └────────────────────────────────┘      │ tasks, doctor           │
                                                        └───────┬────────────────┘
                                                                │
                          ┌─────────────────────────────────────▼──────────────┐
                          │ platforms/*  (one adapter per platform family)     │
                          │ detect → scan (items + evidence) → preview         │
                          └───────┬──────────────────────────────┬─────────────┘
                                  │                              │
                  ┌───────────────▼──────────┐      ┌────────────▼─────────────┐
                  │ formats/* (pure readers) │      │ previews/* (PNG, meshes) │
                  └───────────────┬──────────┘      └──────────────────────────┘
                                  │
                  ┌───────────────▼──────────────────────────────┐
                  │ core/byte_sources.py: read-only byte access  │
                  │ (files, raw CD sectors, CSO, ZIP members)    │
                  └──────────────────────────────────────────────┘
```

## Folders and their job

| Path | Job |
| --- | --- |
| `cutcontent/core/folders.py` | Which folders may be read (environment variable, mounted shares, configured folders, demo folder) and the check that enforces it, including symbolic links. |
| `cutcontent/core/byte_sources.py` | Read-only access to bytes: files opened with `O_RDONLY`, raw 2352-byte CD sectors, slices. Nothing in the project opens game files for writing. |
| `cutcontent/core/virtual_files.py` | A list of files inside a game (PAK, disc, folder), including files hidden by later archives. |
| `cutcontent/core/content_items.py` | The evidence model: four separate levels per item, each with status, method and basis. |
| `cutcontent/core/scan_report.py` | Reports and recorded runtime evidence (stored in the data directory, merged on load). |
| `cutcontent/core/content_search.py` | Preserves a free investigation question and searches actual inventory, metadata and supported decoded text, with explicit coverage. |
| `cutcontent/core/decoded_scenes.py` | Validates decoded map geometry and original-file provenance, registers previews and gives archive subscenes their own evidence cards. |
| `cutcontent/core/release_history.py` | Source-linked publication assessments, separated by data, playable-content and whole-project scope. |
| `cutcontent/core/game_launch.py` | Fixed, verified browser-engine launch and bounded read-only source sessions. |
| `cutcontent/core/native_gameplay.py` | Separately installed interpreter sessions, bounded real inputs, actual frame/audio capture and private saves. |
| `cutcontent/core/developer_menus.py` | Exact-build recipes consisting of ordinary inputs, offered only after observed execution. |
| `cutcontent/core/service.py` | The shared core for CLI and GUI. |
| `cutcontent/formats/` | Pure readers and small builders (the builders create self-made test data). |
| `cutcontent/formats/cartridge_file_table.py` | Cartridge header, bounded filename/allocation tables, overlay IDs and banner decoding. Keeps out-of-bounds entries separate from readable files. |
| `cutcontent/platforms/cartridge_file_table.py` | Cartridge inventory and previews. Never treats the absence of a name reference as proof that a file is unused; games can load files by numeric ID. |
| `cutcontent/platforms/` | Adapters for the Quake engine, cartridge layouts, disc file systems and generic PC folders. |
| `cutcontent/platforms/generic_artifact.py` | Detection-only fallback for an explicitly selected unknown file; does not claim to decode it. |
| `cutcontent/previews/` | Conversion of levels and models to JSON meshes for three.js. |
| `cutcontent/web/` | Local server and the static web interface (`static/`). |
| `cutcontent/demo/` | Self-made demo game and the LibreQuake download. |
| `skills/` | Agent skills: the question-led umbrella workflow plus one skill per phase. Complete copies in `.claude/skills/` and `.agents/skills/`; `skill install` also installs at user scope. |
| `scripts/check_publication.py` | Blocks game data, private paths, tokens and non-noreply commits before publishing. |
| `tests/` | Unit and integration tests with self-made data; `browser_acceptance.py` for the browser run. |
| `docs/LOCAL_INTERPRETER.md` | Describes the optional separately installed interpreter and its availability check. Its source and binary are outside this checkout. |

A new map reader can also register actual geometry using the shared scene
boundary, without implementing every platform feature first. Source hashes,
decoder provenance and a distinct child card keep the conversion tied to its
actual input. The [question-led workflow](QUESTION_LED_INVESTIGATIONS.md)
describes the investigation from free question to visible result.

## Adding a platform adapter

1. Write a reader in `cutcontent/formats/` that works on a `ByteSource` and never writes.
2. Add a builder for a small self-made test image (in the reader module or in `tests/fixture_builders.py`).
3. Write the adapter in `cutcontent/platforms/`: `detect`, `scan` (create `ContentItem`s
   and set evidence honestly; use `unknown` or `not_analysed` when a check is impossible),
   `preview` and `format_support` (state exactly what was tested).
4. Register it in `cutcontent/platforms/__init__.py`, add tests, regenerate
   `docs/FORMAT_SUPPORT.md` with `bin/cutcontent formats --markdown`.

## Data that is written

Only inside the data directory (`CUT_CONTENT_DATA_DIR` or `~/.local/share/cut-content-anything`):
`reports/`, `report-summaries/`, `evidence/`, `investigations/`, `decoded-scenes/`,
`release-history/`, `source-hash-cache/`, `runtime/`, `private-saves/`,
`skill-backups/`, `library.json`, `settings.json`, the `demo/` folder and optional
`engines/` builds. Explicit private scene exports and user-scope skill installs
write to the destinations named in those commands. Library lists read small report
summaries; full asset reports are read when a build is opened. Older reports get
their summaries on first use. Changed reports or scene registrations invalidate
their summaries; rescanning retains registered child scenes and recorded evidence.
