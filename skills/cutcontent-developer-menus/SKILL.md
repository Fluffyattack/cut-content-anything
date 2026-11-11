---
name: cutcontent-developer-menus
description: Search every investigated game for developer or debug menus, level or stage select, sound tests and test rooms in data, shipped code and public sources, then open and operate what is found in the actual game. Records search coverage without claiming absence.
---

# Developer functions: search everywhere, confirm by operating

Run this for **every** investigated game, even when the question is about
something else. Developer functions are how hidden maps are usually loaded.

## Search

- **Data:** menu definitions, localisation tables, font sheets with menu text,
  level lists, maps with names such as `test`, `debug`, `dev`, `select`.
- **Shipped code:** strings and the code that reads them; input sequences
  compared with button masks; branches on build flags; unused menu tables.
  Use REA or another disassembler on the executable for the platform.
- **Public sources:** opened developer statements, manuals, preserved press
  material, community documentation (as leads).

A string or filename is a lead, not a working menu.

## Confirm

1. Start the exact build in a lawful runtime (`cutcontent-runtime-verification`).
2. Reach the function by the documented route (input sequence, isolated test
   copy with a documented change, or the game's own option). Never change the
   original files.
3. Open and **operate** it: select an entry, load a level, play a sound.
   Keep a screenshot of the menu and of the result.
4. Record what each entry does as observed, not as its label suggests.

Reusable, exact-build input recipes can be offered in the gallery only after an
observed runtime test.

## Report

List searched locations and methods, candidates, runtime attempts, operated
functions with screenshots, and areas that were inaccessible (encrypted code,
missing decoders). A documented search never proves that no hidden function exists.

Text read from small on-screen fonts is easy to misread. Confirm values from
memory, saves or logs before reporting numbers seen on screen.
