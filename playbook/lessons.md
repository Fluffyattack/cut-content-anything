# Lessons

Short, general lessons from real investigations. Add yours with the situation
that taught it (without private details).

1. **Screens are not measurements.** Numbers read from a tiny debug font in a
   screenshot were wrong. Raw memory and save comparisons replaced them. Read
   values through a second channel.
2. **A completed level is not a saved level.** Finishing a hidden level in a
   handheld game showed the victory screen, but the save stayed identical to a
   fresh one: the level had no progress record. Compare saves, do not assume.
3. **Equal fields are not equal memory.** After normal play, the compared save
   fields matched while other memory differed. Claim exactly what was compared.
4. **A large analysis can time out; a second method can still answer.** When a
   decompiler project exceeded its time limit on a small machine, targeted
   disassembly with GNU binutils traced the same writer function.
5. **Child scenes do not inherit evidence.** A map decoded from inside an archive
   gets its own card; the archive's usage and release history are not the map's.
6. **Emulated input needs realistic signals.** Weak synthetic noise did not
   trigger a microphone mechanic; the emulator's own pinned test buffer did.
7. **A typo can hide content.** A stored sound was unused because the game code
   asked for a name one letter different.
8. **Released does not mean playable.** Hidden maps ship inside released
   archives all the time; the release scope matters.
