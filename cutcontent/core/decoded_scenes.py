"""A shared, checked scene boundary for built-in and agent-written decoders.

Decoded game geometry stays private. Source hashes bind a conversion to the
selected local build; they do not establish an unused/unreleased/runtime claim.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
from pathlib import Path
import struct

from cutcontent.core.settings import data_directory, write_json_atomically
from cutcontent.core.content_items import ContentItem, Preview

SCENE_SCHEMA = "cutcontent.scene.v1"
MAXIMUM_SCENE_BYTES = 128 * 1024 * 1024
MAXIMUM_VERTICES = 2_000_000


def file_sha256(path: Path) -> str:
    path = path.resolve()
    information = path.stat()
    signature = [information.st_dev, information.st_ino, information.st_size,
                 information.st_mtime_ns, information.st_ctime_ns]
    cache_key = hashlib.sha256(str(path).encode()).hexdigest()
    cache_path = data_directory() / "source-hash-cache" / (cache_key + ".json")
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        digest_value = cached.get("sha256", "")
        if cached.get("signature") == signature and len(digest_value) == 64 and all(character in "0123456789abcdef" for character in digest_value):
            return digest_value
    except (OSError, ValueError):
        pass
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat()
    if [after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns] != signature:
        raise ValueError("The source file changed while its digest was being read.")
    value = digest.hexdigest()
    write_json_atomically(cache_path, {"signature": signature, "sha256": value})
    return value


def _scene_directory() -> Path:
    return data_directory() / "decoded-scenes"


def _image(value: str) -> int:
    if not isinstance(value, str) or not value.startswith("data:image/png;base64,"):
        raise ValueError("Scene textures must be embedded PNG images, not external addresses.")
    raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError("A scene texture is not a valid PNG header.")
    width, height = struct.unpack_from(">II", raw, 16)
    if not 1 <= width <= 8192 or not 1 <= height <= 8192:
        raise ValueError("Scene textures must fit within 8192 by 8192 pixels.")
    return width * height * 4


def _floats(value: str, multiple: int) -> tuple[bytes, list[float]]:
    if not isinstance(value, str):
        raise ValueError("Scene arrays use base64-encoded little-endian 32-bit floats.")
    raw = base64.b64decode(value, validate=True)
    if len(raw) % (4 * multiple):
        raise ValueError("A scene coordinate array has an incomplete element.")
    values = [number for (number,) in struct.iter_unpack("<f", raw)]
    if any(not math.isfinite(number) or abs(number) > 1e12 for number in values):
        raise ValueError("Scene coordinates must be finite and within the supported range.")
    return raw, values


def validate_scene(scene: dict) -> dict:
    if not isinstance(scene, dict):
        raise ValueError("A decoded scene must be an object.")
    textures, groups = scene.get("textures"), scene.get("groups")
    if not isinstance(textures, list) or not 1 <= len(textures) <= 4096 or not isinstance(groups, list) or not 1 <= len(groups) <= 10000:
        raise ValueError("A scene needs actual textures/materials and triangle groups within the supported limits.")
    decoded_texture_bytes = _image(scene.get("lightmap", {}).get("image", ""))
    for texture in textures:
        decoded_texture_bytes += _image(texture.get("image", ""))
    if decoded_texture_bytes > 96 * 1024 * 1024:
        raise ValueError("The decoded scene textures exceed the 96 MiB viewer limit.")
    vertex_count = 0
    minimum = [math.inf] * 3
    maximum = [-math.inf] * 3
    for group in groups:
        texture = group.get("texture")
        if not isinstance(texture, int) or isinstance(texture, bool) or not 0 <= texture < len(textures):
            raise ValueError("A triangle group refers to an unknown material.")
        _, positions = _floats(group.get("positions"), 9)
        vertices = len(positions) // 3
        if not vertices:
            raise ValueError("An empty triangle group is not map geometry.")
        vertex_count += vertices
        if vertex_count > MAXIMUM_VERTICES:
            raise ValueError("The scene exceeds two million vertices; export spatial sections separately.")
        for field in ("uv", "light_uv"):
            raw, _ = _floats(group.get(field), 2)
            if len(raw) != vertices * 2 * 4:
                raise ValueError("Each vertex needs matching texture and light coordinates.")
        for index, value in enumerate(positions):
            axis = index % 3
            minimum[axis] = min(minimum[axis], value)
            maximum[axis] = max(maximum[axis], value)
        group["vertex_count"] = vertices
    # Imported collision data has no implicit engine semantics. A free camera
    # works on every decoded mesh; the Quake hull walker is a separate format.
    scene["collision"] = None
    scene["entities"] = []
    scene["spawn"] = None
    scene["layout"] = "Decoded game geometry"
    scene["bounds"] = {"min": minimum, "max": maximum}
    scene["statistics"] = {"triangles": vertex_count // 3, "faces": vertex_count // 3, "hidden_faces": 0}
    diagonal = math.sqrt(sum((high - low) ** 2 for low, high in zip(minimum, maximum)))
    scene["navigation"] = {"speed": max(.1, min(10000, diagonal / 15)), "far": max(1000, diagonal * 4)}
    return scene


def _verify_inputs(report: dict, inputs: list[dict]) -> None:
    if not isinstance(inputs, list) or not 1 <= len(inputs) <= 128:
        raise ValueError("Record the source files actually read by the decoder.")
    root = Path(report["path"]).resolve()
    for entry in inputs:
        original = Path(entry["path"]).expanduser()
        source = original.resolve()
        inside = source == root if root.is_file() else root in source.parents
        if original.is_symlink() or not inside or not source.is_file():
            raise ValueError("Scene input provenance points outside the selected game.")
        if file_sha256(source) != entry.get("sha256"):
            raise ValueError("Scene source bytes differ from the recorded decoder inputs.")


def register_decoded_scene(build_id: str, item_id: str, package_path: Path) -> dict:
    from cutcontent.core.scan_report import load_report
    report = load_report(build_id)
    if report is None:
        raise ValueError("Scan the game first.")
    item = next((item for item in report["items"] if item["id"] == item_id), None)
    if item is None or item["evidence"]["present_in_data"]["status"] != "yes":
        raise ValueError("Associate the scene with a present source item from this game.")
    if package_path.stat().st_size > MAXIMUM_SCENE_BYTES:
        raise ValueError("Export scene packages smaller than 128 MiB.")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("schema") != SCENE_SCHEMA or package.get("build_id") != build_id or package.get("item_id") != item_id:
        raise ValueError("The scene package must name its schema and exact source build/item.")
    provenance = package.get("provenance", {})
    if not provenance.get("decoder") or not provenance.get("basis"):
        raise ValueError("Document the decoder and how it derived the geometry from the source.")
    _verify_inputs(report, provenance.get("inputs"))
    scene_name = package.get("scene_name", "")
    if not isinstance(scene_name, str) or len(scene_name) > 500 or any(ord(character) < 32 for character in scene_name):
        raise ValueError("Use a readable internal scene name without control characters.")
    if not scene_name and item["kind"] not in ("map", "model"):
        raise ValueError("A map decoded from an archive needs scene_name so its evidence is separate from the parent container.")
    package["scene"] = validate_scene(package.get("scene"))
    scene_id = hashlib.sha256(json.dumps(package, sort_keys=True).encode()).hexdigest()[:24]
    write_json_atomically(_scene_directory() / (scene_id + ".json"), package)
    index_path = _scene_directory() / "builds" / (build_id + ".json")
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        index = {}
    target_item_id = item_id
    if scene_name:
        identity = item_id + scene_name + "".join(sorted(entry["sha256"] for entry in provenance["inputs"]))
        target_item_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
        previous = index.get(item_id)
        if previous and not previous.get("scene_name"):
            index.pop(item_id)  # retire an old container-wide proxy, retain its private package
    index[target_item_id] = {"item_id": target_item_id, "source_item_id": item_id, "scene_name": scene_name,
                            "scene_id": scene_id, "decoder": provenance["decoder"], "basis": provenance["basis"],
                            "triangles": package["scene"]["statistics"]["triangles"], "source_verified": True}
    write_json_atomically(index_path, index)
    return index[target_item_id]


def attach_decoded_scenes(report: dict) -> None:
    try:
        index = json.loads((_scene_directory() / "builds" / (report["build_id"] + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    original_items = {item["id"]: item for item in report.get("items", [])}
    for item in original_items.values():
        if item["id"] in index and not index[item["id"]].get("scene_name") and item["kind"] in ("map", "model"):
            item["decoded_scene"] = index[item["id"]]
            item["kind"] = "map"
            item["preview"] = {"viewer": "map3d", "supported": True, "reason": "A source-bound decoder export is available."}
    for item_id, registration in index.items():
        scene_name = registration.get("scene_name")
        parent = original_items.get(registration.get("source_item_id"))
        if not scene_name or parent is None:
            continue
        location = {key: parent.get("location", {}).get(key, "") for key in ("container", "container_path")}
        location["internal_path"] = parent["name"] + " ! " + scene_name
        child = ContentItem("map", scene_name, location,
                            {"type": "decoded_scene", "source_item_id": parent["id"], "scene_id": registration["scene_id"]},
                            Preview("map3d", True), item_id=item_id,
                            details={"source_container_item": parent["name"], "decoder": registration["decoder"],
                                     "conversion_basis": registration["basis"]})
        child.set_evidence("present_in_data", "yes", "Actual decoded subscene from the identified source container; original input digests were checked.")
        child.set_evidence("possibly_unused", "unknown", "Use of the parent container does not establish use or non-use of this subscene.", "none")
        from cutcontent.platforms.shared_analysis import name_hint
        hint = name_hint(scene_name)
        if hint:
            child.finding_reasons.append(hint)
        record = child.to_dict()
        record["decoded_scene"] = registration
        report["items"].append(record)
    counts = {}
    for item in report["items"]:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    report["statistics"]["items_by_kind"] = counts
    report["statistics"]["items"] = len(report["items"])
    findings = {}
    for item in report["items"]:
        if item["is_finding"]:
            findings[item["kind"]] = findings.get(item["kind"], 0) + 1
    report["statistics"]["findings_by_kind"] = findings
    report["statistics"]["findings"] = sum(findings.values())


def decoded_scene_preview(report: dict, item: dict) -> bytes:
    scene_id = item["decoded_scene"]["scene_id"]
    if not isinstance(scene_id, str) or len(scene_id) != 24 or any(character not in "0123456789abcdef" for character in scene_id):
        raise ValueError("Invalid registered scene identity.")
    path = _scene_directory() / (scene_id + ".json")
    if path.stat().st_size > MAXIMUM_SCENE_BYTES:
        raise ValueError("Registered scene exceeds the supported size.")
    package = json.loads(path.read_text(encoding="utf-8"))
    _verify_inputs(report, package["provenance"]["inputs"])
    return json.dumps(validate_scene(package["scene"])).encode()


def export_existing_scene(build_id: str, item_id: str, destination: Path, source_files: list[Path]) -> dict:
    from cutcontent.core.scan_report import load_report
    from cutcontent.core.service import preview_item
    report = load_report(build_id)
    if report is None:
        raise ValueError("Scan the game first.")
    if destination.exists():
        raise ValueError("Use a new private export filename.")
    source_root = Path(report["path"]).resolve()
    export_path = destination.expanduser().resolve()
    checkout = Path(__file__).resolve().parents[2]
    if checkout == export_path or checkout in export_path.parents:
        raise ValueError("Decoded game scenes are private; store exports outside the source checkout.")
    if export_path == source_root or source_root.is_dir() and source_root in export_path.parents:
        raise ValueError("Store decoded exports outside the original game directory.")
    inputs = [{"path": str(path.expanduser().resolve()), "sha256": file_sha256(path.expanduser().resolve())} for path in source_files]
    _verify_inputs(report, inputs)
    scene = json.loads(preview_item(build_id, item_id).body)
    validate_scene(scene)
    package = {"schema": SCENE_SCHEMA, "build_id": build_id, "item_id": item_id, "scene": scene,
               "provenance": {"decoder": "cutcontent:" + report["adapter"],
                              "basis": "Actual built-in source decoder output, converted to the shared triangle-scene boundary.", "inputs": inputs}}
    write_json_atomically(export_path, package)
    return {"path": str(export_path), "triangles": scene["statistics"]["triangles"], "source_files": len(inputs)}
