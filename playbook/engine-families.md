# Engine and platform families

Where content usually hides, and what this project already reads. "Built in"
means a reader exists in `cutcontent/`; everything else is a decoder task.
`cutcontent formats` is the authoritative support list.

| Family | Containers and assets | Where to look for references | Built in |
| --- | --- | --- | --- |
| Quake engine (PC) | PAK archives; BSP levels; MDL models; SPR sprites; WAV sounds | QuakeC in `progs.dat`/`qwprogs.dat`; BSP entity lumps; `trigger_changelevel` exits | Full reference adapter, browser game start |
| Handheld cartridges with a file table | Header, file name table and file allocation table; overlays; banner icon and titles | Code strings in the main binaries and overlays; level lists in data | Inventory, banner, tiles, code strings; optional local interpreter |
| Disc images (ISO 9660, parameter-file formats, tree-directory DVD formats) | File system, executables, archives inside | Executable strings; game-specific archives | Detection, file listing, name references against unencrypted executables |
| Discs with encrypted partitions | Partition table | Not readable without keys; reported as not covered | Detection only |
| Generic PC folders | Any | Executable strings | Detection, listing, name references |

## Hints for families without a reader yet

These are starting points; confirm everything in the actual build.

- **WAD-based engines:** levels are groups of lumps after a marker lump; check
  which marker names the episode or map list in the executable uses.
- **Unity:** scenes listed in the build settings are compiled into level files;
  assets referenced only by removed scenes can remain in shared asset files or
  bundles. Managed code (C#) can be read with a .NET decompiler.
- **Unreal Engine:** packages (`.pak`, newer `.utoc`/`.ucas`) contain maps
  (`.umap`) and assets; maps not listed in the game's map list are candidates.
- **Source engine:** VPK archives, BSP levels, `.res` and script files;
  map lists in `cfg` files and chapter definitions.
- **Script-driven 2D engines** (visual novel and RPG makers): maps and labels
  that no jump, call or transfer command targets.

Add a row when you write a reader, with the game that taught you.
