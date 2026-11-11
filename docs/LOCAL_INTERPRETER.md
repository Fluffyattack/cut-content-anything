# Optional local game interpreter

The investigation skill can ask the local gallery to start a cartridge game in
a separately installed interpreter. The interpreter executes the real game,
accepts buttons and touch input, and produces screen frames, audio and private
saves. The scanner and its previews work without this component.

The interpreter's source, build scripts, binary and upstream dependencies are
not distributed in this checkout. On the machine used for the documented local
tests, they are kept in a private add-on. This public project cannot build or
install that add-on for a new user. An independently supplied compatible player
may be selected with `CUT_CONTENT_CARTRIDGE_INTERPRETER_DIR`.

The selected directory must contain an executable named `cartridge_player` and
a `build.json` manifest with `protocol_version: 1` and the executable's
`player_sha256`. Run `bin/cutcontent doctor` to check availability and the hash.
The gallery offers the launch control only for a supported scanned cartridge
and an available interpreter. Developer-menu input recipes are kept in the
private data directory and offered only for an exact matching game-file hash.

Game files are opened read-only. Screen captures, audio, logs and saves are
written under `CUT_CONTENT_DATA_DIR` or the user's local application-data
directory. A real frame capture establishes only what appeared under the
recorded input and test conditions. Scans and asset previews are separate from
game execution. See [the evidence model](../GLOSSARY.md) and
[third-party notices](../THIRD_PARTY_NOTICES.md).
