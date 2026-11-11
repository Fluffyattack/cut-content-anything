# Tools

| Tool | Use | Notes |
| --- | --- | --- |
| `cutcontent` | Scan, search, gallery, evidence, release history, directory, MCP | Python 3.10+, standard library only |
| Playwright with Chromium | Browser acceptance tests of the gallery and the browser engine | Optional, only for tests |
| Emscripten | Building the browser game engine from pinned sources | See `docs/GAME_LAUNCH.md` |
| REA | Reverse engineering MCP server | Optional |
| Ghidra | Decompiler | Optional; set time limits |
| GNU binutils | Disassembly for many architectures | Fast second method |
| An emulator for the platform | Runtime verification | Installed by the owner |

Every download comes from the official publisher at a fixed version, and its
SHA-256 is compared before use. Installer scripts are read before they run and
are never piped straight into a shell. Software is installed only with the
owner's permission.
