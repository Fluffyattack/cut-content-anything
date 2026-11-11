"""Adapter for games built on the Quake engine (id Tech 1), e.g. LibreQuake.

What it reads: a *game directory* (``id1`` or a mod folder) with ``pak0.pak``,
``pak1.pak`` ... and loose files, exactly in the order the engine searches them
(numbered PAK files in unbroken order, later ones win, then loose files).

What it judges, all by static analysis of the files:

- **levels** that cannot be reached from the start level through level exits
  (``trigger_changelevel``) and are not named in game code or configuration files;
- **models, sprites, sounds** whose file names appear nowhere in the game code
  (``progs.dat``), in level entities or in the short list of names the engine
  itself loads;
- **music tracks** that no level selects;
- **entities** that can never appear: excluded from every difficulty level and
  deathmatch, of a class the game code cannot create, or placed outside the level;
- **entity types** the game code can create but no level places;
- **textures** stored inside a level but not used by any surface;
- **files that are overridden** by a later PAK file and therefore never loaded.
"""

from __future__ import annotations

import difflib
import os
import re
from collections import deque
from pathlib import Path

from cutcontent.core.byte_sources import LazyFileByteSource
from cutcontent.core.content_items import ContentItem, Preview
from cutcontent.core.png_writer import encode_png, greyscale_palette, indexed_to_rgba, palette_swatch_png
from cutcontent.core.scan_report import ScanReport
from cutcontent.core.virtual_files import VirtualFile, VirtualFileSystem
from cutcontent.formats import quake_bsp, quake_images, quake_model, quake_pak, quake_progs
from cutcontent.platforms.base import Detection, FormatSupport, PlatformAdapter, PreviewError, PreviewResult
from cutcontent.platforms.shared_analysis import name_hint
from cutcontent.previews import quake_level_mesh, quake_model_mesh

# File names the original engine source code (GPL release) loads by itself,
# independent of the game code: temporary-entity sounds and lightning models
# (cl_tent.c), ambient sounds (snd_dma.c), menu sounds (menu.c), chat sound (console.c).
ENGINE_LOADED_SOUNDS = {
    "weapons/r_exp3.wav",
    "weapons/tink1.wav",
    "weapons/ric1.wav",
    "weapons/ric2.wav",
    "weapons/ric3.wav",
    "ambience/water1.wav",
    "ambience/wind2.wav",
    "misc/menu1.wav",
    "misc/menu2.wav",
    "misc/menu3.wav",
    "misc/talk.wav",
}
ENGINE_LOADED_MODELS = {"progs/bolt.mdl", "progs/bolt2.mdl", "progs/bolt3.mdl"}
START_LEVEL = "start"  # the main menu's "New game" runs "map start"

# Compiler tool textures: the level compiler removes their surfaces on purpose.
TOOL_TEXTURE_NAMES = {"clip", "skip", "hint", "hintskip", "trigger", "origin", "nodraw", "null"}
SPAWN_FUNCTION_PREFIXES = ("monster_", "item_", "weapon_", "func_", "trigger_", "misc_", "ambient_", "light_", "info_", "path_", "target_")
MESSAGE_PATTERN = re.compile(r"^[A-Za-z][^\x00-\x08]{12,}$")
TEXT_FILE_EXTENSIONS = {"cfg", "rc", "txt", "md", "adoc"}
MUSIC_EXTENSIONS = {"ogg", "mp3", "wav", "flac"}
LOOSE_FILE_LIMIT = 20000
PAK_NAME = re.compile(r"^pak(\d+)\.pak$", re.IGNORECASE)

KNOWN_DATA_SIZES = {18689235: "Quake shareware data (pak0.pak, version 1.06)", 34257856: "Quake registered data (pak1.pak)"}


def numbered_pak_files(directory: Path) -> list[Path]:
    """pak0.pak, pak1.pak, ... in the order the engine opens them (it stops at the first gap)."""
    by_number = {}
    try:
        for entry in os.scandir(directory):
            match = PAK_NAME.match(entry.name)
            if match and entry.is_file():
                by_number[int(match.group(1))] = Path(entry.path)
    except OSError:
        return []
    result = []
    number = 0
    while number in by_number:
        result.append(by_number[number])
        number += 1
    return result


def looks_like_game_directory(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    if (directory / "pak0.pak").is_file() or (directory / "PAK0.PAK").is_file():
        return True
    return (directory / "progs.dat").is_file() and (directory / "maps").is_dir()


class QuakeGameData:
    """All files of one game directory, as the engine sees them."""

    def __init__(self, path: Path):
        self.path = path
        self.warnings: list[str] = []
        self.pak_files: list[Path] = []
        self.vfs = VirtualFileSystem(str(path))
        if path.is_file():
            self.game_directory = path.parent
            self.pak_files = [path]
            for virtual_file in quake_pak.open_pak_files(path):
                self.vfs.add(virtual_file)
        else:
            self.game_directory = path
            self._add_loose_files()
            self.pak_files = numbered_pak_files(path)
            for pak_path in self.pak_files:
                for virtual_file in quake_pak.open_pak_files(pak_path):
                    self.vfs.add(virtual_file)
            unloaded = sorted(
                entry.name
                for entry in os.scandir(path)
                if entry.name.lower().endswith(".pak") and Path(entry.path) not in self.pak_files
            )
            if unloaded:
                self.warnings.append(
                    "These PAK files are not loaded by the original engine (only pak0.pak, pak1.pak, ... without gaps are) "
                    f"and were not analysed: {', '.join(unloaded)}"
                )
        self._palette: bytes | None = None

    def _add_loose_files(self) -> None:
        count = 0
        root = str(self.path)
        for directory, subdirectories, files in os.walk(root):
            subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
            for file_name in sorted(files):
                if file_name.lower().endswith(".pak") and directory == root:
                    continue
                full_path = os.path.join(directory, file_name)
                if os.path.islink(full_path) or not os.path.isfile(full_path):
                    continue
                relative = os.path.relpath(full_path, root).replace(os.sep, "/")
                size = os.path.getsize(full_path)
                self.vfs.add(VirtualFile(relative, size, LazyFileByteSource(full_path, size), 0, "loose file", full_path))
                count += 1
                if count >= LOOSE_FILE_LIMIT:
                    self.warnings.append(f"Stopped listing loose files after {LOOSE_FILE_LIMIT} files.")
                    return

    def palette(self) -> bytes:
        if self._palette is None:
            palette_file = self.vfs.get("gfx/palette.lmp")
            data = palette_file.read() if palette_file else b""
            if len(data) >= quake_images.PALETTE_SIZE:
                self._palette = data[: quake_images.PALETTE_SIZE]
            else:
                self._palette = greyscale_palette()
                self.warnings.append("No gfx/palette.lmp was found; images are shown in grey.")
        return self._palette

    def find_file(self, path: str, container: str | None = None) -> VirtualFile | None:
        if container:
            for shadowed in self.vfs.shadowed:
                if shadowed.hidden.path.lower() == path.lower() and shadowed.hidden.container == container:
                    return shadowed.hidden
        return self.vfs.get(path)


_GAME_DATA_CACHE: dict[str, tuple[tuple, QuakeGameData]] = {}


def cached_game_data(game_directory: Path) -> QuakeGameData:
    """Previews ask for one file at a time; re-reading every PAK directory each time would be slow."""
    folder = game_directory if game_directory.is_dir() else game_directory.parent
    try:
        signature = tuple(sorted((entry.name, entry.stat().st_size, entry.stat().st_mtime_ns) for entry in os.scandir(folder)))
    except OSError:
        signature = ()
    key = str(game_directory)
    cached = _GAME_DATA_CACHE.get(key)
    if cached and cached[0] == signature:
        return cached[1]
    data = QuakeGameData(game_directory)
    data.palette()
    if len(_GAME_DATA_CACHE) >= 4:
        _GAME_DATA_CACHE.pop(next(iter(_GAME_DATA_CACHE)))
    _GAME_DATA_CACHE[key] = (signature, data)
    return data


def resolve_game_directory(path: Path) -> Path:
    if path.is_file():
        return path
    if looks_like_game_directory(path):
        return path
    for name in ("id1", "ID1", "lq1"):
        if looks_like_game_directory(path / name):
            return path / name
    raise ValueError(f"{path} is not a Quake game directory (no pak0.pak, no progs.dat with maps)")


def guess_title(game_directory: Path) -> str:
    folder = game_directory if game_directory.is_dir() else game_directory.parent
    for licence_name in ("docs/COPYING", "docs/README.md", "docs/CREDITS"):
        licence_file = folder / licence_name
        try:
            if licence_file.is_file() and "librequake" in licence_file.read_text(encoding="utf-8", errors="ignore").lower():
                return "LibreQuake"
        except OSError:
            pass
    pak0 = folder / "pak0.pak"
    if pak0.is_file() and os.path.getsize(pak0) in KNOWN_DATA_SIZES:
        return "Quake"
    demo_readme = folder.parent / "README.txt"
    try:
        if demo_readme.is_file() and demo_readme.read_text(encoding="utf-8", errors="ignore").startswith("Cut Content Anything demo data"):
            return "Cut Content Anything demo"
    except OSError:
        pass
    parent_name = folder.parent.name if folder.name.lower() in ("id1", "lq1") else folder.name
    return parent_name or folder.name


def map_name(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()


class QuakeAdapter(PlatformAdapter):
    identifier = "quake"
    display_name = "Quake engine games (PAK, BSP, MDL)"
    platform_family = "pc"

    # ------------------------------------------------------------------ detection
    def detect(self, path: Path) -> list[Detection]:
        try:
            if path.is_file():
                if path.suffix.lower() != ".pak":
                    return []
                with open(path, "rb") as handle:
                    if handle.read(4) != quake_pak.PAK_MAGIC:
                        return []
                if looks_like_game_directory(path.parent):
                    return []  # the folder is detected instead
                game_directory = path
            else:
                game_directory = resolve_game_directory(path)
        except (OSError, ValueError):
            return []
        title = guess_title(game_directory)
        folder = game_directory if game_directory.is_dir() else game_directory.parent
        pak_files = numbered_pak_files(folder) if game_directory.is_dir() else [game_directory]
        label = f"{folder.name} folder, {len(pak_files)} PAK file(s)"
        return [Detection(self.identifier, "PC (Quake engine)", "Quake game directory", title, label, str(game_directory), 0.95)]

    # ----------------------------------------------------------------------- scan
    def scan(self, path: Path) -> ScanReport:
        game_directory = resolve_game_directory(path)
        data = QuakeGameData(game_directory)
        palette = data.palette()
        analysis = QuakeAnalysis(data, palette)
        analysis.run()
        report = ScanReport(
            path=str(game_directory),
            adapter=self.identifier,
            platform="PC (Quake engine)",
            format_name="Quake game directory (PAK/BSP/MDL)",
            title=guess_title(game_directory),
            build_label=f"{game_directory.name}: " + (", ".join(p.name for p in data.pak_files) or "loose files only"),
            items=analysis.items,
            limits=analysis.limits,
            warnings=data.warnings + analysis.warnings,
            details=analysis.details,
            game_launch=game_launch_status(data),
        )
        return report

    # -------------------------------------------------------------------- preview
    def preview(self, path: Path, item: dict, options: dict) -> PreviewResult:
        data = cached_game_data(resolve_game_directory(path))
        palette = data.palette()
        reference = item["reference"]
        reference_type = reference.get("type")

        if reference_type == "embedded_texture":
            level = self._read_level(data, reference["map"])
            for texture in level.textures:
                if texture and texture.name == reference["texture"]:
                    png, _, _ = quake_level_mesh.texture_png(texture, palette)
                    return PreviewResult("image/png", png)
            raise PreviewError("The texture was not found in the level any more.")

        if reference_type == "wad_lump":
            wad_file = data.find_file(reference["wad"])
            if not wad_file:
                raise PreviewError("The WAD archive was not found any more.")
            wad_data = wad_file.read()
            for lump in quake_images.read_wad_directory(wad_data):
                if lump.name == reference["lump"]:
                    image = quake_images.read_wad_image(wad_data, lump)
                    if image:
                        return PreviewResult("image/png", self._indexed_png(image, palette))
            raise PreviewError("The picture could not be decoded.")

        if reference_type == "level_text":
            level = self._read_level(data, reference["map"])
            lines = [f"Messages in {reference['map']} (entity number, class, target name):", ""]
            for index, entity in enumerate(level.entities):
                if entity.get("message"):
                    target = f" [{entity['targetname']}]" if entity.get("targetname") else ""
                    lines.append(f"#{index} {entity.get('classname', '?')}{target}: {entity['message'].replace(chr(10), ' / ')}")
            return PreviewResult("text/plain; charset=utf-8", "\n".join(lines).encode("utf-8"))

        if reference_type == "game_text":
            return PreviewResult("text/plain; charset=utf-8", self._game_text(data, reference["path"]).encode("utf-8"))

        if reference_type in ("entity", "spawn_function", "information"):
            raise PreviewError("This item is described in the details panel; there is no separate file to show.")

        virtual_file = data.find_file(reference["path"], reference.get("container"))
        if virtual_file is None:
            raise PreviewError("The file was not found any more. Scan the game again.")
        extension = virtual_file.extension
        lower_path = virtual_file.path.lower()

        if extension == "bsp":
            level = quake_bsp.read_level(virtual_file.read())
            lit_file = data.find_file(virtual_file.path[:-4] + ".lit")
            preview = quake_level_mesh.build_level_preview(level, palette, lit_file.read() if lit_file else None)
            preview["name"] = virtual_file.path
            return json_result(preview)
        if extension == "mdl":
            model = quake_model.read_model(virtual_file.read())
            if options.get("thumbnail"):
                return PreviewResult("image/png", quake_model_mesh.skin_png(model, palette))
            preview = quake_model_mesh.build_model_preview(model, palette)
            preview["name"] = virtual_file.path
            return json_result(preview)
        if extension == "spr":
            frames = quake_images.read_sprite_frames(virtual_file.read())
            return PreviewResult("image/png", self._indexed_png(quake_images.combine_side_by_side(frames), palette))
        if lower_path.endswith("palette.lmp"):
            return PreviewResult("image/png", palette_swatch_png(virtual_file.read()))
        if lower_path.endswith("colormap.lmp"):
            raw = virtual_file.read()[: 256 * 64]
            return PreviewResult("image/png", encode_png(256, len(raw) // 256, indexed_to_rgba(raw, palette)))
        if extension == "lmp":
            image = quake_images.read_lmp_picture(virtual_file.name, virtual_file.read())
            return PreviewResult("image/png", self._indexed_png(image, palette))
        if extension == "wav":
            return PreviewResult("audio/wav", virtual_file.read())
        if extension == "ogg":
            return PreviewResult("audio/ogg", virtual_file.read())
        if extension == "mp3":
            return PreviewResult("audio/mpeg", virtual_file.read())
        if extension in TEXT_FILE_EXTENSIONS:
            return PreviewResult("text/plain; charset=utf-8", virtual_file.read(2_000_000).decode("latin-1").encode("utf-8"))
        if extension == "png":
            return PreviewResult("image/png", virtual_file.read())
        raise PreviewError(f"There is no preview for '.{extension}' files.")

    @staticmethod
    def _indexed_png(image: quake_images.IndexedImage, palette: bytes) -> bytes:
        return encode_png(image.width, image.height, indexed_to_rgba(image.pixels, palette, image.transparent_index))

    @staticmethod
    def _read_level(data: QuakeGameData, path: str) -> quake_bsp.QuakeLevel:
        virtual_file = data.find_file(path)
        if not virtual_file:
            raise PreviewError("The level was not found any more.")
        return quake_bsp.read_level(virtual_file.read())

    @staticmethod
    def _game_text(data: QuakeGameData, path: str) -> str:
        virtual_file = data.find_file(path)
        if not virtual_file:
            raise PreviewError("The game code file was not found any more.")
        code = quake_progs.read_game_code(virtual_file.read())
        messages = [text for text in code.strings if MESSAGE_PATTERN.match(text) and " " in text]
        lines = [
            f"Text strings in {path} that look like messages shown to players ({len(messages)} of {len(code.strings)} strings).",
            "Whether each message is ever shown depends on the game code; this list does not judge that.",
            "",
        ]
        lines += [text.replace("\n", "\\n") for text in messages]
        return "\n".join(lines)

    # ------------------------------------------------------------ format support
    def format_support(self) -> list[FormatSupport]:
        tested = (
            "Automated tests with self-made demo data generated by the test suite (PAK, level, model, sound, game code). "
            "Locally also with LibreQuake v0.09-beta 'lite' (BSD-3-Clause art); that data is not part of this repository."
        )
        return [
            FormatSupport(
                "PC (Quake engine)",
                "Quake game directory: PAK archives and loose files",
                ".pak, folders such as id1/",
                "tested",
                "PAK directories, engine search order, overridden files.",
                "References from game code, entities and configuration files; overridden files.",
                "All contained files by type (see the following rows).",
                "Mod folders are scanned on their own, not layered on top of id1. Other *.pak names (not pak0..N) are listed but not analysed.",
                tested,
            ),
            FormatSupport(
                "PC (Quake engine)",
                "Levels (BSP)",
                ".bsp (version 29, BSP2, 2PSB)",
                "tested",
                "Entities, surfaces, embedded textures, light maps (.lit colour light), BSP tree for point contents.",
                "Reachability through level exits from 'start'; never-spawning entities; entities outside the level; unused embedded textures; entity types never placed.",
                "'Explore in 3D': free camera through the textured, light-mapped level with entity markers, plus a walk mode that uses the level's own player collision hull (gravity, steps, jumping). Brush models (b_*.bsp) can be turned around.",
                "Animated textures are shown as still images; sky is a flat texture; doors, lifts and triggers do not move or block in walk mode. BSP2 and 2PSB are implemented but only tested with version 29 levels. "
                "'Open in game' starts a separately built Qwasm engine after its browser acceptance test; tested with LibreQuake's lq_e0m1 and dev levels.",
                tested,
            ),
            FormatSupport(
                "PC (Quake engine)",
                "Models (MDL)",
                ".mdl (IDPO version 6)",
                "tested",
                "Skins, skin groups, texture coordinates with seam handling, triangles, single and grouped frames.",
                "Name references from game code, entities and the engine's own list.",
                "Full 3D orbit view with texture, every skin, every animation (10 frames per second like the engine, interpolated).",
                "Model flags (rotation, trails) are listed, not animated. Other model formats (MD2, MD3, IQM) are not supported.",
                tested,
            ),
            FormatSupport(
                "PC (Quake engine)",
                "Sprites, pictures, WAD archives, palettes",
                ".spr, .lmp, gfx.wad",
                "tested",
                "Sprite frames and groups, pictures, WAD2 pictures and textures, palette and colour map.",
                "Sprites: name references. Pictures and WAD lumps are drawn by the engine's menu code, which is not analysed.",
                "Images with palette colours and transparency, zoomable.",
                "WAD3 (Half-Life) uses its own palettes and is not decoded.",
                tested,
            ),
            FormatSupport(
                "PC (Quake engine)",
                "Sounds and music",
                ".wav, music/trackNN.ogg",
                "tested",
                "File inventory.",
                "Sounds: name references (game code paths are relative to sound/). Music: track numbers chosen by levels.",
                "Played directly in the browser.",
                "Game code can switch music tracks with numbers that are invisible to static analysis.",
                tested,
            ),
            FormatSupport(
                "PC (Quake engine)",
                "Game code",
                "progs.dat, qwprogs.dat (version 6)",
                "tested",
                "String table and function names.",
                "Spawn functions versus entity classes placed in levels.",
                "Text strings that look like player-facing messages.",
                "No decompilation and no control-flow analysis; FTE extended formats (version 7) are refused.",
                tested,
            ),
        ]


def is_tool_texture(name: str) -> bool:
    lowered = name.lower().lstrip("*")
    return lowered in TOOL_TEXTURE_NAMES or lowered.endswith("skip")


def json_result(payload: dict) -> PreviewResult:
    import json

    return PreviewResult("application/json", json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def game_launch_status(data: QuakeGameData | None = None) -> dict:
    from cutcontent.platforms.browser_engines import quake_browser_engine_status

    status = quake_browser_engine_status()
    if data is not None:
        missing = [name for name in ("progs.dat", "gfx.wad", "gfx/palette.lmp", "gfx/colormap.lmp") if data.vfs.get(name) is None]
        if missing:
            status["available"] = False
            status["reason"] = "This data supports previews but is missing engine resources: " + ", ".join(missing)
    return status


class QuakeAnalysis:
    """Runs every static check for one game directory and produces report items."""

    def __init__(self, data: QuakeGameData, palette: bytes):
        self.data = data
        self.palette = palette
        self.items: list[ContentItem] = []
        self.limits: list[str] = []
        self.warnings: list[str] = []
        self.details: dict = {}

        self.code_strings: set[str] = set()
        self.code_sources: list[str] = []
        self.all_functions: set[str] = set()
        self.spawn_functions: set[str] = set()
        self.configuration_levels: set[str] = set()
        self.configuration_demos: set[str] = set()
        self.entity_values: set[str] = set()
        self.placed_classes: dict[str, list[str]] = {}
        self.level_exits: dict[str, set[str]] = {}
        self.music_tracks_used: dict[int, list[str]] = {}
        self.levels: dict[str, quake_bsp.QuakeLevel] = {}

    # ---------------------------------------------------------------- inputs
    def _read_game_code(self) -> None:
        for name in ("progs.dat", "qwprogs.dat"):
            virtual_file = self.data.vfs.get(name)
            if not virtual_file:
                continue
            try:
                code = quake_progs.read_game_code(virtual_file.read())
            except quake_progs.ProgsFormatError as error:
                self.warnings.append(f"{name} could not be read: {error}")
                continue
            self.code_sources.append(name)
            self.code_strings.update(text.lower().replace("\\", "/") for text in code.strings)
            if name == "progs.dat":
                self.all_functions = {function.lower() for function in code.function_names()}
                self.spawn_functions = {function.lower() for function in code.functions_only_callable_by_name()}
            self.details.setdefault("game_code", {})[name] = {"strings": len(code.strings), "functions": len(code.functions)}
        if "progs.dat" not in self.code_sources:
            self.limits.append("No readable progs.dat: model, sound and entity-class references from game code could not be checked.")

    def _read_configuration(self) -> None:
        """Level and demo names that start-up and configuration files load by command."""
        for virtual_file in self.data.vfs.files():
            if "/" in virtual_file.path or virtual_file.extension not in ("cfg", "rc"):
                continue
            text = virtual_file.read(1_000_000).decode("latin-1").lower()
            for command, arguments in re.findall(r"\b(map|changelevel|startdemos|playdemo|timedemo)\s+([^;\n]*)", text):
                names = [word.strip('"') for word in arguments.split()]
                if command in ("map", "changelevel"):
                    self.configuration_levels.update(names[:1])
                else:
                    self.configuration_demos.update(names)

    def _read_levels(self) -> None:
        for virtual_file in self.data.vfs.files():
            lower = virtual_file.path.lower()
            if not (lower.startswith("maps/") and lower.endswith(".bsp")):
                continue
            try:
                level = quake_bsp.read_level(virtual_file.read())
            except (quake_bsp.BspFormatError, Exception) as error:  # damaged levels are reported, not fatal
                self.warnings.append(f"{virtual_file.path} could not be read: {error}")
                continue
            name = map_name(lower)
            self.levels[lower] = level
            exits = set()
            for entity in level.entities:
                classname = entity.get("classname", "").lower()
                self.placed_classes.setdefault(classname, []).append(name)
                for key, value in entity.items():
                    if key in ("model", "noise", "noise1", "noise2", "noise3", "noise4", "map", "wad"):
                        self.entity_values.add(value.lower().replace("\\", "/"))
                if classname == "trigger_changelevel" and entity.get("map"):
                    exits.add(entity["map"].lower())
                if classname == "worldspawn":
                    try:
                        track = int(float(entity.get("sounds", "0")))
                    except ValueError:
                        track = 0
                    if track > 0:
                        self.music_tracks_used.setdefault(track, []).append(name)
            self.level_exits[name] = exits

    # ------------------------------------------------------------ judgements
    def _reachable_levels(self) -> dict[str, list[str]]:
        """Breadth-first walk through level exits starting at the start level."""
        if START_LEVEL not in self.level_exits:
            return {}
        paths = {START_LEVEL: [START_LEVEL]}
        queue = deque([START_LEVEL])
        while queue:
            current = queue.popleft()
            for target in sorted(self.level_exits.get(current, ())):
                if target not in paths:
                    paths[target] = paths[current] + [target]
                    queue.append(target)
        return paths

    def _new_item(self, kind: str, virtual_file: VirtualFile, preview: Preview, thumbnail: bool = False) -> ContentItem:
        reference = {"type": "file", "path": virtual_file.path}
        item = ContentItem(kind, virtual_file.path, virtual_file.location(), reference, preview, thumbnail=thumbnail)
        item.set_evidence("present_in_data", "yes", f"Stored as {virtual_file.path} in {virtual_file.container} ({virtual_file.size} bytes).")
        hint = name_hint(virtual_file.path)
        if hint:
            item.finding_reasons.append(hint)
        self.items.append(item)
        return item

    def _judge_name_reference(self, item: ContentItem, keys: list[str], extra: set[str] | None = None) -> bool:
        sources = []
        for key in keys:
            if key in self.code_strings:
                sources.append("game code")
            if key in self.entity_values:
                sources.append("level entities")
            if extra and key in extra:
                sources.append("the engine's own file list")
        if sources:
            item.set_evidence("possibly_unused", "no", f"'{keys[0]}' is named in {', '.join(sorted(set(sources)))}.")
            item.set_evidence("reachable_in_normal_play", "unknown", "Referenced, but whether the referencing code runs in normal play was not checked.", "none")
            return True
        if not self.code_sources:
            item.set_evidence("possibly_unused", "unknown", "No game code could be read, so references could not be checked.", "none")
            return False
        item.set_evidence(
            "possibly_unused",
            "yes",
            f"'{keys[0]}' does not appear in {', '.join(self.code_sources)}, in any level entity or in the engine's own file list.",
        )
        item.set_evidence("reachable_in_normal_play", "unlikely", "Nothing found that would load it.")
        item.finding_reasons.append("No reference found in game code, levels or the engine's own file list.")
        item.limits.append("Mods, console commands and other engines can still load the file by name.")
        return False

    def run(self) -> None:
        self._read_game_code()
        self._read_configuration()
        self._read_levels()
        reachable = self._reachable_levels()
        if not reachable:
            self.limits.append(f"There is no maps/{START_LEVEL}.bsp, so level reachability through level exits could not be determined.")
        self.details["reachable_levels"] = {name: " → ".join(path) for name, path in sorted(reachable.items())}
        self.details["level_exits"] = {name: sorted(targets) for name, targets in sorted(self.level_exits.items())}
        self.details["pak_files"] = [str(path) for path in self.data.pak_files]

        texture_items: dict[tuple[str, int], ContentItem] = {}
        for virtual_file in self.data.vfs.files():
            self._inventory_file(virtual_file, reachable, texture_items)
        self._add_overridden_files()
        self._add_entity_type_findings()
        self._add_missing_references()
        self.limits.extend(
            [
                "All judgements are static: files were read, the game was not run. 'Loaded under test conditions' stays 'not checked' until a runtime test is recorded.",
                "Images in gfx/ and gfx.wad are drawn by the engine's menu and status bar code, which is not analysed.",
            ]
        )

    def _inventory_file(self, virtual_file: VirtualFile, reachable: dict, texture_items: dict) -> None:
        lower = virtual_file.path.lower()
        extension = virtual_file.extension

        if extension == "bsp" and lower.startswith("maps/"):
            self._inventory_level(virtual_file, reachable, texture_items)
        elif extension == "mdl":
            problem = self._model_problem(virtual_file)
            item = self._new_item("model", virtual_file, Preview("model3d", problem is None, problem or ""), thumbnail=problem is None)
            if problem is None:
                item.details = self._model_details(virtual_file)
            self._judge_name_reference(item, [lower], ENGINE_LOADED_MODELS)
        elif extension == "spr":
            problem = self._sprite_problem(virtual_file)
            item = self._new_item("sprite", virtual_file, Preview("image", problem is None, problem or ""), thumbnail=problem is None)
            self._judge_name_reference(item, [lower])
        elif extension == "wav" and lower.startswith("sound/"):
            item = self._new_item("sound", virtual_file, Preview("audio", True))
            self._judge_name_reference(item, [lower[len("sound/") :]], ENGINE_LOADED_SOUNDS)
        elif extension in MUSIC_EXTENSIONS and lower.startswith("music/"):
            self._inventory_music(virtual_file)
        elif extension == "lmp":
            problem = self._picture_problem(virtual_file)
            item = self._new_item("image", virtual_file, Preview("image", problem is None, problem or ""), thumbnail=problem is None)
            item.set_evidence("possibly_unused", "not_analysed", "Pictures are drawn by the engine's menu and status bar code, which is not analysed.", "none")
        elif extension == "wad":
            self._inventory_wad(virtual_file)
        elif extension in TEXT_FILE_EXTENSIONS:
            item = self._new_item("text", virtual_file, Preview("text", True))
            if lower in ("quake.rc", "default.cfg"):
                item.set_evidence("possibly_unused", "no", "Executed by the engine at start-up.")
        elif extension == "dat" and lower in ("progs.dat", "qwprogs.dat"):
            item = ContentItem(
                "text",
                f"Messages in {virtual_file.path}",
                virtual_file.location(),
                {"type": "game_text", "path": virtual_file.path},
                Preview("text", True),
            )
            item.set_evidence("present_in_data", "yes", f"Text strings stored in {virtual_file.path} ({virtual_file.container}).")
            item.set_evidence("possibly_unused", "not_analysed", "Whether each message is shown depends on game code paths, which are not analysed.", "none")
            self.items.append(item)
            code_item = self._new_item("code", virtual_file, Preview("info", False, "Compiled game code; it is not decompiled. The message list is a separate item."))
            if lower == "progs.dat":
                code_item.set_evidence("possibly_unused", "no", "The engine always loads progs.dat.")
            else:
                code_item.set_evidence("possibly_unused", "no", "Loaded by QuakeWorld servers, not by the single-player engine.")
        elif extension == "dem":
            item = self._new_item("file", virtual_file, Preview("info", False, "Recorded demos can only be played by the engine."))
            demo = map_name(lower)
            if demo in self.configuration_demos:
                item.set_evidence("possibly_unused", "no", "Named in a start-up configuration file (e.g. 'startdemos').")
            else:
                item.set_evidence("possibly_unused", "yes", "Not named in quake.rc or other configuration files.")
                item.finding_reasons.append("Demo recording that no start-up file plays.")
        elif extension == "lit":
            pass  # coloured light is shown as part of its level
        elif extension == "png":
            self._new_item("image", virtual_file, Preview("image", True), thumbnail=True)
        else:
            self._new_item("file", virtual_file, Preview("info", False, f"No preview for '.{extension or 'no extension'}' files."))

    @staticmethod
    def _model_problem(virtual_file: VirtualFile) -> str | None:
        try:
            quake_model.read_model(virtual_file.read())
        except quake_model.ModelFormatError as error:
            return f"The model could not be read: {error}."
        return None

    @staticmethod
    def _model_details(virtual_file: VirtualFile) -> dict:
        model = quake_model.read_model(virtual_file.read())
        return {
            "triangles": len(model.triangles),
            "vertices": model.vertex_count,
            "frames": len(model.frames),
            "skins": len(model.skins),
            "skin_size": f"{model.skin_width} x {model.skin_height}",
            "animations": ", ".join(f"{animation['name']} ({animation['frame_count']})" for animation in model.animations[:12]),
        }

    @staticmethod
    def _sprite_problem(virtual_file: VirtualFile) -> str | None:
        try:
            quake_images.read_sprite_frames(virtual_file.read())
        except (quake_images.QuakeImageError, Exception) as error:
            return f"The sprite could not be read: {error}."
        return None

    @staticmethod
    def _picture_problem(virtual_file: VirtualFile) -> str | None:
        lower = virtual_file.path.lower()
        if lower.endswith("palette.lmp"):
            return None if virtual_file.size >= quake_images.PALETTE_SIZE else "The palette file is too short."
        if lower.endswith("colormap.lmp"):
            return None if virtual_file.size >= 256 * 2 else "The colour map file is too short."
        try:
            quake_images.read_lmp_picture(virtual_file.name, virtual_file.read())
        except quake_images.QuakeImageError:
            if lower.endswith("pop.lmp"):
                return "gfx/pop.lmp is not a picture here: the engine only checks that the file exists (to tell the full version from the shareware version)."
            return "This .lmp file is not a picture (its size does not match a picture header)."
        return None

    def _inventory_level(self, virtual_file: VirtualFile, reachable: dict, texture_items: dict) -> None:
        lower = virtual_file.path.lower()
        name = map_name(lower)
        level = self.levels.get(lower)
        is_brush_model = name.startswith("b_")
        item = self._new_item("model" if is_brush_model else "map", virtual_file, Preview("map3d", level is not None, "" if level else "The level could not be read."))
        if level is None:
            return
        item.details = {
            "layout": level.layout,
            "entities": len(level.entities),
            "faces": len(level.faces),
            "embedded_textures": sum(1 for texture in level.textures if texture),
            "title": next((entity.get("message", "") for entity in level.entities if entity.get("classname") == "worldspawn"), ""),
            "exits_to": sorted(self.level_exits.get(name, ())),
        }
        if is_brush_model:
            item.details["brush_model"] = True
            self._judge_name_reference(item, [lower])
        else:
            mentioned_in_code = name in self.code_strings or lower in self.code_strings
            mentioned_in_configuration = name in self.configuration_levels
            if name in reachable:
                route = " → ".join(reachable[name])
                item.set_evidence("possibly_unused", "no", f"Reachable through level exits: {route}.")
                item.set_evidence("reachable_in_normal_play", "likely", f"Static route from the start level: {route}. This route has not been executed in a normal-play test.")
                item.details["normal_access_search"] = {"status": "route_found", "route": route, "method": "static"}
            elif mentioned_in_code or mentioned_in_configuration:
                where = "game code" if mentioned_in_code else "a configuration file"
                item.set_evidence("possibly_unused", "no", f"The level name appears in {where}.")
                item.set_evidence("reachable_in_normal_play", "unknown", f"No level exit leads here, but {where} names it (for example deathmatch rotation or a menu).")
            elif reachable:
                item.set_evidence("possibly_unused", "yes", "No access found in the checked level-exit graph, literal game-code strings and configuration references.")
                item.set_evidence("reachable_in_normal_play", "unknown", "No regular access found. Checked level exits from start and literal name references in game code and configuration files. Additional routes remain possible.")
                item.details["normal_access_search"] = {"status": "not_found", "method": "static",
                    "scope": "Level-exit graph from start; literal game-code strings; configuration references",
                    "limitation": "No exhaustive normal-play or dynamic-loader proof."}
                item.finding_reasons.append("No regular access found in the checked exits, game-code strings and configuration references.")
                item.limits.append("Deathmatch servers and menus of modern engines can list every level file.")
        self._inventory_embedded_textures(virtual_file, level, texture_items, name)
        if not is_brush_model:
            self._inventory_entities(virtual_file, level, name)
            self._inventory_level_text(virtual_file, level, item)

    def _inventory_level_text(self, virtual_file: VirtualFile, level: quake_bsp.QuakeLevel, level_item: ContentItem) -> None:
        """Messages that entities show to the player (level title, door hints, secrets ...)."""
        messages = [(index, entity) for index, entity in enumerate(level.entities) if entity.get("message")]
        if not messages:
            return
        reference = {"type": "level_text", "map": virtual_file.path}
        item = ContentItem("text", f"Text in {virtual_file.path} ({len(messages)} messages)", virtual_file.location(), reference, Preview("text", True))
        item.set_evidence("present_in_data", "yes", f"'message' keys of {len(messages)} entities in {virtual_file.path} ({virtual_file.container}).")
        unused_status = level_item.evidence["possibly_unused"]
        if unused_status.status == "yes":
            item.set_evidence("possibly_unused", "yes", "The level itself is possibly unused, and so is its text.")
            item.finding_reasons.append("Text of a level that nothing leads to.")
        else:
            item.set_evidence("possibly_unused", "not_analysed", "Whether each message is shown depends on how its entity is triggered, which is not analysed.", "none")
        item.details = {"messages": len(messages)}
        self.items.append(item)

    def _inventory_embedded_textures(self, virtual_file: VirtualFile, level: quake_bsp.QuakeLevel, texture_items: dict, level_name: str) -> None:
        used_indices = {projection.texture_index for projection in (level.projections[face.projection_index] for face in level.faces if 0 <= face.projection_index < len(level.projections))}
        used_names = {level.textures[index].name.lower() for index in used_indices if 0 <= index < len(level.textures) and level.textures[index]}
        for texture in level.textures:
            if texture is None:
                continue
            fingerprint = (texture.name.lower(), hash(texture.pixels))
            unused_here = (
                texture.index not in used_indices
                and not self._is_animation_frame_of_used(texture.name, used_names)
                and not is_tool_texture(texture.name)
            )
            item = texture_items.get(fingerprint)
            if item is None:
                reference = {"type": "embedded_texture", "map": virtual_file.path, "texture": texture.name}
                level_location = virtual_file.location()
                location = {
                    "container": level_location["container"],
                    "container_path": level_location["container_path"],
                    "internal_path": level_location["internal_path"],
                    "texture": texture.name,
                    "level_offset_in_container": level_location["offset"],
                }
                item = ContentItem("texture", texture.name, location, reference, Preview("image", texture.pixels is not None, "" if texture.pixels else "Texture data is stored outside the level (WAD)."), thumbnail=True)
                item.details = {"width": texture.width, "height": texture.height, "levels": [], "unused_in_levels": []}
                item.set_evidence("possibly_unused", "no", "Used by at least one surface.")
                texture_items[fingerprint] = item
                self.items.append(item)
            item.details["levels"].append(level_name)
            if unused_here:
                item.details["unused_in_levels"].append(level_name)
        for item in {id(entry): entry for entry in texture_items.values()}.values():
            levels, unused = item.details["levels"], item.details["unused_in_levels"]
            item.set_evidence("present_in_data", "yes", f"Embedded in {len(levels)} level(s): {', '.join(sorted(set(levels))[:8])}.")
            item.finding_reasons = [reason for reason in item.finding_reasons if not reason.startswith("Embedded")]
            if unused and len(unused) == len(levels):
                item.set_evidence("possibly_unused", "yes", f"Stored in {', '.join(sorted(set(unused)))} but no surface of those levels uses it.")
                item.set_evidence("reachable_in_normal_play", "no", "No visible surface shows this texture.")
                item.finding_reasons.append("Embedded in a level but not used by any surface.")
            elif unused:
                item.details["note"] = f"Unused copy in: {', '.join(sorted(set(unused)))}"

    @staticmethod
    def _is_animation_frame_of_used(name: str, used_names: set[str]) -> bool:
        lowered = name.lower()
        if len(lowered) > 2 and lowered[0] == "+":
            stem = lowered[2:]
            return any(used.startswith("+") and used[2:] == stem for used in used_names)
        return False

    def _inventory_entities(self, virtual_file: VirtualFile, level: quake_bsp.QuakeLevel, level_name: str) -> None:
        world = level.models[0] if level.models else None
        never_spawn = quake_bsp.SPAWNFLAG_NOT_EASY | quake_bsp.SPAWNFLAG_NOT_NORMAL | quake_bsp.SPAWNFLAG_NOT_HARD | quake_bsp.SPAWNFLAG_NOT_DEATHMATCH
        for index, entity in enumerate(level.entities):
            classname = entity.get("classname", "")
            reasons, limits = [], []
            reachable_status, reachable_basis = "unknown", "Not determined."
            flags = quake_bsp.spawn_flags(entity)
            if classname and classname != "worldspawn" and (flags & never_spawn) == never_spawn:
                reasons.append("Excluded from every difficulty level and from deathmatch (spawn flags 256+512+1024+2048), so it never appears.")
                reachable_status, reachable_basis = "no", "The engine removes it on every difficulty level and in deathmatch."
            if self.all_functions and classname and classname.lower() not in self.all_functions:
                reasons.append(f"The game code has no spawn function '{classname}'; the engine removes the entity when the level loads.")
                reachable_status, reachable_basis = "no", "No spawn function in progs.dat."
            origin = quake_bsp.parse_vector(entity.get("origin"))
            if origin and world and classname.startswith(("monster_", "item_", "weapon_")):
                outside = any(origin[axis] < world.mins[axis] - 1 or origin[axis] > world.maxs[axis] + 1 for axis in range(3))
                if outside:
                    reasons.append("Placed outside the level's bounding box.")
                    reachable_status, reachable_basis = "unlikely", "Outside the level geometry."
                else:
                    probes = [(origin[0], origin[1], origin[2] + lift) for lift in (0, 8, 16, 24)]
                    if all(level.point_contents(probe) == quake_bsp.CONTENTS_SOLID for probe in probes):
                        reasons.append("Its position is inside solid geometry.")
                        limits.append("Checked with the level's drawing hull at four heights above the origin; the engine drops some items to the floor first.")
                        reachable_status, reachable_basis = "unlikely", "Inside solid geometry."
            if not reasons:
                continue
            reference = {"type": "entity", "map": virtual_file.path, "index": index}
            location = dict(virtual_file.location(), entity_index=index, origin=entity.get("origin", ""))
            item = ContentItem("entity", f"{classname or 'entity'} #{index} in {level_name}", location, reference, Preview("map3d", True))
            item.details = {"entity": dict(entity), "map_item_path": virtual_file.path}
            item.set_evidence("present_in_data", "yes", f"Entity number {index} in the entity list of {virtual_file.path} ({virtual_file.container}).")
            item.set_evidence("possibly_unused", "yes", reasons[0])
            item.set_evidence("reachable_in_normal_play", reachable_status, reachable_basis)
            item.finding_reasons.extend(reasons)
            item.limits.extend(limits + ["Game code can also create, move or remove entities at runtime."])
            self.items.append(item)

    def _inventory_music(self, virtual_file: VirtualFile) -> None:
        item = self._new_item("music", virtual_file, Preview("audio", True))
        match = re.search(r"track(\d+)", virtual_file.name.lower())
        if not match:
            item.set_evidence("possibly_unused", "unknown", "Not a numbered music track.", "none")
            return
        track = int(match.group(1))
        levels = self.music_tracks_used.get(track)
        if levels:
            item.set_evidence("possibly_unused", "no", f"Selected by level(s): {', '.join(sorted(set(levels)))} (worldspawn 'sounds' {track}).")
        else:
            item.set_evidence("possibly_unused", "yes", f"No level selects track {track}.")
            item.finding_reasons.append(f"Music track {track} is not selected by any level.")
            item.limits.append("Game code can switch music tracks with numbers (e.g. for the intermission or finale) that static analysis cannot see.")

    def _inventory_wad(self, virtual_file: VirtualFile) -> None:
        container = self._new_item("file", virtual_file, Preview("info", False, "WAD archive; its pictures are listed as separate items."))
        container.set_evidence("possibly_unused", "not_analysed", "The engine loads gfx.wad for the status bar and console.", "none")
        try:
            wad_data = virtual_file.read()
            lumps = quake_images.read_wad_directory(wad_data)
        except quake_images.QuakeImageError as error:
            self.warnings.append(f"{virtual_file.path}: {error}")
            return
        for lump in lumps:
            image = quake_images.read_wad_image(wad_data, lump)
            if image is None:
                continue
            reference = {"type": "wad_lump", "wad": virtual_file.path, "lump": lump.name}
            location = dict(virtual_file.location(), lump=lump.name, lump_offset=lump.offset)
            item = ContentItem("image", f"{virtual_file.path}: {lump.name}", location, reference, Preview("image", True), thumbnail=True)
            item.details = {"width": image.width, "height": image.height}
            item.set_evidence("possibly_unused", "not_analysed", "Drawn by the engine's status bar and menu code, which is not analysed.", "none")
            self.items.append(item)

    def _add_overridden_files(self) -> None:
        for shadowed in self.data.vfs.shadowed:
            hidden, winner = shadowed.hidden, shadowed.winner
            reference = {"type": "file", "path": hidden.path, "container": hidden.container}
            kind = {"mdl": "model", "wav": "sound", "lmp": "image", "spr": "sprite", "bsp": "map"}.get(hidden.extension, "file")
            viewer = {"model": "model3d", "sound": "audio", "image": "image", "sprite": "image", "map": "map3d"}.get(kind, "info")
            preview = Preview(viewer, viewer != "info", "" if viewer != "info" else "No preview for this file type.")
            item = ContentItem(kind, f"{hidden.path} (older copy in {hidden.container})", hidden.location(), reference, preview, thumbnail=kind in ("image", "sprite", "model"))
            item.set_evidence("present_in_data", "yes", f"Stored as {hidden.path} in {hidden.container} ({hidden.size} bytes).")
            item.set_evidence("possibly_unused", "yes", f"{winner.container} contains a file with the same name, and the engine loads that one.")
            item.set_evidence("reachable_in_normal_play", "no", f"The engine always picks the copy in {winner.container}.")
            item.finding_reasons.append(f"Overridden by the copy in {winner.container}; this version is never loaded.")
            item.details = {"overridden_by": winner.container, "same_size": winner.size == hidden.size}
            self.items.append(item)

    def _missing_references(self) -> list[tuple[str, str, str]]:
        """(expected path, kind, where it is named) for referenced files that are not in the data."""
        missing = []
        for text in sorted(self.code_strings):
            if text.endswith((".mdl", ".spr", ".bsp")) and "/" in text and not self.data.vfs.get(text):
                missing.append((text, "model" if not text.startswith("maps/") else "map", "game code"))
            elif text.endswith(".wav") and not self.data.vfs.get("sound/" + text):
                missing.append(("sound/" + text, "sound", "game code"))
        known_levels = {map_name(path) for path in self.levels}
        for level, targets in sorted(self.level_exits.items()):
            for target in sorted(targets):
                if target not in known_levels:
                    missing.append((f"maps/{target}.bsp", "map", f"a level exit in {level}"))
        return missing

    def _add_missing_references(self) -> None:
        missing = self._missing_references()
        if not missing:
            return
        missing_paths = [path for path, _, _ in missing]
        for path, kind, where in missing:
            reference = {"type": "information", "path": path}
            location = {"container": "(not in the data)", "internal_path": path, "referenced_by": where}
            item = ContentItem(kind, f"{path} (referenced, missing)", location, reference, Preview("info", False, "The file is not in the data, so there is nothing to show."))
            item.set_evidence("present_in_data", "no", f"Named in {where}, but no PAK file or folder contains {path}.")
            item.set_evidence("possibly_unused", "not_analysed", "The content itself is absent; only the reference remains.", "none")
            item.set_evidence("reachable_in_normal_play", "no", "The file does not exist in this build.")
            item.finding_reasons.append(f"Referenced by {where} but missing from the data: a trace of removed or not yet added content.")
            item.limits.append("Other builds, mission packs or full releases may contain the file.")
            self.items.append(item)
        # Unreferenced files whose names are almost the same as a missing reference are often typos.
        for item in self.items:
            if item.evidence["possibly_unused"].status != "yes" or item.reference.get("type") != "file":
                continue
            close = difflib.get_close_matches(item.reference["path"].lower(), missing_paths, n=1, cutoff=0.9)
            if close:
                note = f"Almost the same name is referenced but missing: {close[0]}. The reference may contain a typo, which would make this file unused."
                item.finding_reasons.append(note)
                item.details["similar_missing_reference"] = close[0]

    def _add_entity_type_findings(self) -> None:
        if not self.spawn_functions or not self.levels:
            return
        placed = set(self.placed_classes)
        for function in sorted(self.spawn_functions):
            if not function.startswith(SPAWN_FUNCTION_PREFIXES) or function in placed:
                continue
            reference = {"type": "spawn_function", "name": function}
            location = {"container": "progs.dat", "internal_path": "progs.dat", "function": function}
            item = ContentItem("code", f"Entity type {function}", location, reference, Preview("info", False, "A spawn function in compiled game code; there is nothing to draw."))
            item.set_evidence("present_in_data", "yes", f"progs.dat contains a function named '{function}', which creates entities of this class.")
            item.set_evidence("possibly_unused", "yes", "No level in this build places an entity of this class.")
            item.set_evidence("reachable_in_normal_play", "unknown", "Game code may still create it while playing.", "none")
            item.finding_reasons.append("Entity type the game code can create, but no level places.")
            item.limits.append("Some spawn functions are only called by other game code or are meant for user-made levels.")
            self.items.append(item)
