# Developer functions

Developer and debug menus, level select, sound tests and test rooms are searched
for in every investigated game. They are both findings and tools: they are
often the safest way to load hidden maps in the actual game.

## Where they hide

- Menu tables in data or code whose entries are never added to the visible menu.
- Input checks: a sequence of button masks compared with recent input.
- Build flags: a byte or word that the release build never sets.
- Test maps: names such as `test`, `dev`, `debug`, `sandbox`, `select`.
- Leftover text: menu labels in localisation tables or font atlases.

## Confirming one

1. Locate the code that opens it (disassembler or REA on the shipped executable).
2. Find the lawful route: the game's own input sequence, or a documented change
   in an **isolated copy** (configuration, memory value in the emulator).
3. Open it in the actual game, operate several entries, keep screenshots.
4. Write down what each entry did, as observed.

## Reading numbers from the screen

Small debug fonts are easy to misread, and models describing screenshots can
invent plausible digits. Confirm every number shown on screen through a second
channel (memory, save file, log) before reporting it.

## Reporting coverage

List what was searched, how, and what was inaccessible. A search that found
nothing is a coverage statement, never "the game has no debug menu".
