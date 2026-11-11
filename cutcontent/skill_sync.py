"""Keeps the agent skills identical for Claude Code and Codex.

The single source is the ``skills/`` folder in the repository: one folder per
skill, each with a ``SKILL.md`` and optional reference files. Copies live where
each client looks for project skills:

- Claude Code: ``.claude/skills/<skill name>/``
- Codex:       ``.agents/skills/<skill name>/``

``cutcontent skill sync`` writes the copies; ``cutcontent skill sync --check``
(and the test suite) fails if a copy differs from the source.
``cutcontent skill install`` installs the same skills at user scope.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import shutil
from cutcontent.core.settings import data_directory

MAIN_SKILL_NAME = "cut-content-anything"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_SOURCE = REPOSITORY_ROOT / "skills"
CLIENT_SKILL_FOLDERS = (
    REPOSITORY_ROOT / ".claude" / "skills",
    REPOSITORY_ROOT / ".agents" / "skills",
)


def skill_names() -> list[str]:
    if not SKILLS_SOURCE.is_dir():
        return []
    return sorted(folder.name for folder in SKILLS_SOURCE.iterdir() if (folder / "SKILL.md").is_file())


def _source_files(name: str) -> list[tuple[Path, Path]]:
    root = SKILLS_SOURCE / name
    return [(path.relative_to(root), path) for path in sorted(root.rglob("*"))
            if path.is_file() and not path.is_symlink() and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(root).parts)]


def _copy_matches(destination: Path, source_files: list[tuple[Path, Path]]) -> bool:
    return all((destination / relative).is_file() and (destination / relative).read_bytes() == source.read_bytes()
               for relative, source in source_files)


def skill_copies_status() -> list[tuple[Path, bool]]:
    """One row per skill and client: the copy folder and whether it matches the source."""
    rows = []
    for name in skill_names():
        source_files = _source_files(name)
        for client_folder in CLIENT_SKILL_FOLDERS:
            rows.append((client_folder / name, _copy_matches(client_folder / name, source_files)))
    return rows


def sync_skill_copies() -> list[Path]:
    """Copies every skill to every client location; returns the files that changed."""
    names = skill_names()
    if not names:
        raise FileNotFoundError(f"{SKILLS_SOURCE} has no skills; this command only works inside the repository checkout")
    changed = []
    for name in names:
        for client_folder in CLIENT_SKILL_FOLDERS:
            for relative, source in _source_files(name):
                destination = client_folder / name / relative
                content = source.read_bytes()
                if destination.is_file() and destination.read_bytes() == content:
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
                changed.append(destination)
    return changed


def install_user_skills() -> list[Path]:
    """Install every skill at user scope, backing up a differing existing copy first."""
    names = skill_names()
    if not names:
        raise FileNotFoundError("The shared skill source directory is missing.")
    installed = []
    for name in names:
        source_files = _source_files(name)
        for client, base in (("codex", Path.home() / ".agents" / "skills"), ("claude", Path.home() / ".claude" / "skills")):
            destination = base / name
            if destination.exists() and not _copy_matches(destination, source_files):
                timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = data_directory() / "skill-backups" / client / (name + "-" + timestamp)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(destination, backup)
            for relative, source in source_files:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            installed.append(destination)
    return installed
