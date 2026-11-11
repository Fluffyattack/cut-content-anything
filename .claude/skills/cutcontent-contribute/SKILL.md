---
name: cutcontent-contribute
description: Send what an investigation learned back to the shared repository - directory entries, a game write-up, playbook fixes and generalised readers - without any game data, private paths, screenshots of proprietary games or the owner's personal details. Ends with a draft pull request that the owner has approved.
---

# Contribute: publish reusable results

Do this after every phase that produced something reusable, not only at the end.

## What to send

1. **Directory entry** in `data/directory.json` (schema: `data/SCHEMA.md`).
   Validate with `cutcontent directory validate` (or the MCP tool
   `validate_directory_entry`), then run `cutcontent directory build` and
   add the regenerated `DIRECTORY.md` to the same commit. Set the quality level honestly:
   `runtime-verified` needs a test that actually ran.
2. **Write-up** in `games/<game-slug>/README.md` from `templates/game.md`.
   One folder per game; several builds go into the same write-up.
3. **Decoder notes** from `templates/decoder.md`, and a reusable reader with
   self-made test data if it is general enough.
4. **Playbook fix** when a method turned out incomplete or incorrect, with the game that
   taught it as evidence.
5. A finding that is only `source-reports` is still useful. So is a corrected
   entry or a documented search that found nothing.

## What never goes in

Game files or extracted assets (maps, textures, audio, text dumps, decoded
scene packages), ROMs, disc images, saves, keys, screenshots of proprietary
games, machine reports, local paths with user names, e-mail addresses, tokens.
Each owner decides separately whether a case about one of their games may be
published at all; the default is private.

## How

1. `git checkout -b game/<game-slug>` in the owner's fork.
2. `python3 -m unittest discover -s tests -t tests` and
   `python3 scripts/check_publication.py` must pass.
3. Let the owner review the diff; their GitHub account publishes it.
4. Create a draft pull request from the template (`gh pr create --draft`), covering a single game.
