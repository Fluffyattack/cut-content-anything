---
name: cutcontent-decoder
description: Read unknown game archives and asset formats read-only. Identify containers from bytes, use documentation and binary analysis, build and test a decoder on the real inputs, and export maps through the shared scene package so they open in the gallery.
---

# Decoder: from unknown bytes to a viewable asset

An unsupported format is a task, not a dead end, and never evidence of absence.

## Workflow

1. **Start from the container.** Signature, header fields, table of contents,
   alignment, compression markers. Compare several files of the same type.
2. **Look for authoritative descriptions:** the engine's published source,
   official tools, format documentation, or existing open-source readers with
   compatible licences. Record what you used and its licence.
3. **Use binary analysis where the format is only defined by the game code.**
   Find the loader in the shipped executable (for example with REA or Ghidra),
   follow how it reads the header and entries, and name what you understood.
4. **Write a read-only reader.** Never modify the original; open it read-only
   and bound every length, count and offset by the actual file size. Report
   incomplete or out-of-range entries instead of guessing.
5. **Test privately on the real input.** Check counts, checksums, known names,
   landmarks and rendering against the game. Keep the test reports private.
6. **Show the result.** Maps go through the shared scene package
   (`cutcontent.scene.v1`, see `playbook/gallery-and-scenes.md` or the main
   skill's `references/question-led-investigations.md`):
   `cutcontent scene register BUILD ITEM package.json`, then open the map in
   `cutcontent gui`, operate the viewer and keep a screenshot.
7. **Generalise before publishing.** A reader joins the public tool only with
   tests built from self-made data, a format entry in `docs/FORMAT_SUPPORT.md`
   and the honest support level. Game bytes never go into tests or the repository.

## Never

Decrypt protected content, bypass DRM or anti-cheat, download keys, firmware
or games. Encrypted parts are reported as not covered.

A decoded preview is not a game start. Runtime claims need
`cutcontent-runtime-verification`.
