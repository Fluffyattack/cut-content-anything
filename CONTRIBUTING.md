# Contributing

This page summarises the contribution steps; [AGENTS.md](AGENTS.md) contains
the complete rules for agents.

1. **Work on a branch** of your fork: `game/<game-slug>`, `directory/<what>` or `reader/<format>`.
2. **Directory:** edit `data/directory.json` ([schema](data/SCHEMA.md)), then run
   `bin/cutcontent directory validate` and `bin/cutcontent directory build`, and
   add the regenerated `DIRECTORY.md` to the same commit. Each entry links at
   least one source you opened and records when it was last checked.
3. **Write-ups:** `games/<game-slug>/README.md` from [templates/game.md](templates/game.md).
4. **Readers and decoders:** code in `cutcontent/`, tests with self-made data in
   `tests/`, notes from [templates/decoder.md](templates/decoder.md) and an
   honest row in `docs/FORMAT_SUPPORT.md`.
5. **Playbook:** fix or extend a page in `playbook/` and name the game that showed the problem.
6. Run `python3 -m unittest discover -s tests -t tests` and
   `python3 scripts/check_publication.py`.
7. **Let the owner review the diff**, then create a draft pull request from the
   template, covering a single game.

Please don't:

- add game files or extracted assets (maps, models, textures, audio, text
  dumps, decoded scene packages, ROMs, disc images, saves) or links to download them;
- add screenshots of proprietary games;
- paste personal information (names, e-mail addresses, user names in paths, tokens);
- state a higher quality level than the evidence supports; `unknown` is acceptable;
- call content "unreleased" without checked sources for the scope.

Found something but can't verify it? Open a **"documented content"** issue with
the source; someone's agent will check it in an actual build. Beginning work on a
game with no write-up yet? Open a **"claim a game"** issue to show others what you are working on.
