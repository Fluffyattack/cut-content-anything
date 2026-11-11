# Workspace and privacy

## Where things live

| What | Where | Public? |
| --- | --- | --- |
| The owner's game files | Their own folders, registered with `cutcontent folders add` | Never; always read-only |
| Scans, reports, decoded scenes, saves, runtime captures | The private data folder (`cutcontent doctor` shows it) | Never |
| Case notes for one game | The private data folder or `local/` in the checkout (git-ignored) | Never, unless the owner decides otherwise for that case |
| General format knowledge, readers, methods | `cutcontent/`, `playbook/`, `templates/` | Yes |
| Directory entries and write-ups | `data/directory.json`, `games/` | Yes, without game data or private details |

## Rules

- Original files are opened read-only. Tests that need a change work on an
  isolated copy, and the change is recorded.
- Never download games, ROMs, disc images, BIOS, firmware, keys or leaked builds.
- No circumvention of DRM, copy protection, encryption or anti-cheat.
- Before any push: `python3 scripts/check_publication.py`. It rejects game data
  file types, decoded scene packages, private paths, e-mail addresses and tokens,
  in the files and in the history.
