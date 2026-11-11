#!/usr/bin/env python3
"""Checks the repository before anything is published.

Only known source and documentation file types, plus screenshots, may be
published (an allowlist, so no game data can slip through under any name).
The check fails if the files that would be pushed (tracked files plus new files
that are not ignored) or any commit in the history contain:

- a file type that is not on the allowlist (game data, disc or cartridge images,
  saves, keys, archives, engine binaries, ...);
- text files that are not valid UTF-8 (binary data under a text name);
- very large files;
- private paths, private e-mail addresses or things that look like access tokens;
- decoded game-scene packages;
- commits whose author or committer e-mail is not a GitHub "noreply" address.

Usage: python3 scripts/check_publication.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Source code, documentation and configuration that may be published.
ALLOWED_TEXT_SUFFIXES = {".py", ".md", ".txt", ".js", ".html", ".css", ".toml", ".json", ".yml", ".yaml", ".c", ".cpp", ".h", ".patch", ".sh", ".cfg", ""}
# Binary files are only allowed as screenshots in the documentation.
ALLOWED_BINARY_FOLDER = "docs/screenshots/"
ALLOWED_BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
SIZE_LIMIT = 2_500_000
PRIVATE_TEXT_PATTERNS = [
    (re.compile(r"/home/pi\b"), "a private home folder path"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?:aol|gmail|yahoo|outlook|hotmail|gmx|web)\.[a-z]{2,}", re.IGNORECASE), "a private e-mail address"),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b"), "something that looks like an access token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "a private key"),
]
VENDORED_PREFIX = "cutcontent/web/static/vendor/"


def private_text_problems(path: str, content: bytes) -> list[str]:
    problems = []
    text = content.decode("utf-8", errors="ignore")
    for pattern, description in PRIVATE_TEXT_PATTERNS:
        for match in pattern.finditer(text):
            problems.append(f"{path}: contains {description} ({match.group()[:40]!r})")
    return problems


def private_artifact_problem(path: str, content: bytes) -> str | None:
    try:
        payload = json.loads(content)
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("schema") in ("cutcontent.scene.v1", "cutcontent.asset.v1"):
        return "decoded game-scene packages contain private geometry/assets and must not be published"
    return None


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def files_to_publish() -> list[str]:
    output = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return sorted(path for path in output.split("\0") if path and (ROOT / path).is_file())


def file_type_problem(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix in ALLOWED_TEXT_SUFFIXES:
        return None
    if path.startswith(ALLOWED_BINARY_FOLDER) and suffix in ALLOWED_BINARY_SUFFIXES:
        return None
    return f"file type '{suffix or 'none'}' is not on the publication allowlist (only source, documentation and screenshots may be published)"


def check_files(problems: list[str]) -> int:
    paths = files_to_publish()
    for path in paths:
        full = ROOT / path
        problem = file_type_problem(path)
        if problem:
            problems.append(f"{path}: {problem}")
        size = full.stat().st_size
        if size > SIZE_LIMIT:
            problems.append(f"{path}: {size} bytes is larger than the limit of {SIZE_LIMIT}")
        if size <= SIZE_LIMIT:
            artifact_problem = private_artifact_problem(path, full.read_bytes())
            if artifact_problem:
                problems.append(f"{path}: {artifact_problem}")
        if full.suffix.lower() in ALLOWED_TEXT_SUFFIXES and size <= SIZE_LIMIT:
            content = full.read_bytes()
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"{path}: is not valid UTF-8 text (binary data under a text file name)")
            if not path.startswith(VENDORED_PREFIX) and path != "scripts/check_publication.py":
                problems.extend(private_text_problems(path, content))
    return len(paths)


def check_history(problems: list[str]) -> int:
    try:
        commits = git("rev-list", "--all").split()
    except subprocess.CalledProcessError:
        return 0
    for line in git("log", "--all", "--format=%H %ae %ce").splitlines():
        commit, author, committer = line.split(" ")
        for email in (author, committer):
            if not email.endswith("@users.noreply.github.com") and email != "noreply@github.com":
                problems.append(f"commit {commit[:10]}: e-mail {email} is not a GitHub noreply address")
    seen = set()
    for path in git("log", "--all", "--name-only", "--format=").splitlines():
        if path and path not in seen:
            seen.add(path)
            problem = file_type_problem(path)
            if problem:
                problems.append(f"history contains {path}: {problem}")
    return len(commits)


def main() -> int:
    problems: list[str] = []
    file_count = check_files(problems)
    commit_count = check_history(problems)
    if problems:
        print("Publication check FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"Publication check passed: {file_count} files, {commit_count} commits, all branches and tags.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
