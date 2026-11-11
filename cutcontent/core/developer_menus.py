"""Exact-build developer-menu input recipes, kept outside the source repository.

A recipe is a small JSON file in ``<data directory>/developer-menu-recipes/``.
It holds controller inputs (never game code or assets), the size and SHA-256 of
the one cartridge build it was observed on, and the sources and observation that
back it. A recipe is offered only after the complete read-only cartridge hash
matches, so one observed revision is never generalised to other releases.

Recipe file fields: ``id``, ``title``, ``description``, ``observed``, ``limits``,
``sources`` (list of URLs), ``cartridge_size``, ``cartridge_sha256`` and
``inputs`` with ``start_wait_frames``, ``sequence`` (button names),
``press_frames``, ``final_button`` and ``final_press_frames``.
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from cutcontent.core.settings import data_directory

RECIPE_FOLDER_NAME = "developer-menu-recipes"
BUTTON_BITS = {"a": 0, "b": 1, "select": 2, "start": 3, "right": 4,
               "left": 5, "up": 6, "down": 7, "r": 8, "l": 9, "x": 10, "y": 11}
ALL_BUTTONS_RELEASED = 0xFFF  # the interpreter's key mask is active-low
PUBLIC_FIELDS = ("id", "title", "description", "observed", "limits", "sources")


def recipe_directory() -> Path:
    return data_directory() / RECIPE_FOLDER_NAME


def _valid(recipe: dict) -> bool:
    inputs = recipe.get("inputs", {})
    buttons = list(inputs.get("sequence", [])) + [inputs.get("final_button", "start")]
    return (
        isinstance(recipe.get("id"), str) and recipe["id"]
        and isinstance(recipe.get("cartridge_size"), int)
        and isinstance(recipe.get("cartridge_sha256"), str) and len(recipe["cartridge_sha256"]) == 64
        and all(button in BUTTON_BITS for button in buttons)
    )


def load_recipes() -> list[dict]:
    directory = recipe_directory()
    if not directory.is_dir():
        return []
    recipes = []
    for path in sorted(directory.glob("*.json")):
        try:
            recipe = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(recipe, dict) and _valid(recipe):
            recipes.append(recipe)
    return recipes


@lru_cache(maxsize=16)
def _cartridge_digest(path: str, size: int, modified_nanoseconds: int) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def developer_menu_recipes(path: Path) -> list[dict]:
    """Recipes whose exact cartridge build matches this file (public fields only)."""
    information = path.stat()
    candidates = [recipe for recipe in load_recipes() if recipe["cartridge_size"] == information.st_size]
    if not candidates:
        return []
    digest = _cartridge_digest(str(path), information.st_size, information.st_mtime_ns)
    return [{field: recipe.get(field) for field in PUBLIC_FIELDS} for recipe in candidates if recipe["cartridge_sha256"] == digest]


def developer_menu_commands(recipe_id: str) -> list[str]:
    """Interpreter commands that replay a recipe's button sequence from a fresh boot."""
    recipe = next((entry for entry in load_recipes() if entry["id"] == recipe_id), None)
    if recipe is None:
        raise ValueError("No input sequence is registered for this developer menu.")
    inputs = recipe["inputs"]
    press = int(inputs.get("press_frames", 4))
    commands = [f"step {int(inputs.get('start_wait_frames', 180))}"]
    for button in inputs.get("sequence", []):
        commands += [f"keys {ALL_BUTTONS_RELEASED ^ (1 << BUTTON_BITS[button])}", f"step {press}", f"keys {ALL_BUTTONS_RELEASED}", f"step {press}"]
    final_button = inputs.get("final_button")
    if final_button:
        hold = int(inputs.get("final_press_frames", press))
        commands += [f"keys {ALL_BUTTONS_RELEASED ^ (1 << BUTTON_BITS[final_button])}", f"step {hold}", f"keys {ALL_BUTTONS_RELEASED}", f"step {hold}"]
    return commands
