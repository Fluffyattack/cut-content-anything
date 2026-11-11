# Gallery and shared scenes

`cutcontent gui` serves the gallery on `127.0.0.1:8749`. It reads only the
folders the owner allowed and requires a session token for every API call.

## What it shows

- Levels in a free 3D camera with the level's textures and light maps, plus a
  walk mode with collision. This is a preview, not a game start.
- Models with skins and animations, textures pixel-exact, sounds with waveform,
  text with filtering, raw tiles for cartridges.
- A finding card per item with the four evidence statements, release history,
  sources, and, where available, **Open in game**.

## Shared scene package

Any decoder can produce a private `cutcontent.scene.v1` JSON package that the
gallery opens in the same viewer:

- the exact `build_id` and `item_id`, and for a sub-scene inside an archive its
  internal `scene_name`;
- `provenance`: decoder name and revision, a description of the decoded
  structures, and every original input file with its SHA-256;
- textures as embedded PNG data, an optional light map, and triangle groups
  with base64 little-endian float32 positions and texture coordinates in
  right-handed Y-up space.

```sh
cutcontent scene register BUILD ITEM /private/map.scene.json
```

A sub-scene gets its own card. It does not inherit the parent's evidence.
The viewer checks counts, finite values, material references, memory limits
and input hashes. Scene packages contain game geometry and are never published.
