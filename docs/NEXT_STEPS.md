# Next steps

Agreed with the owner on 2026-11-11, in this order:

1. **Licences** ([decision 0005](adr/0005-licences-for-code-and-shared-knowledge.md)):
   research what MIT for code and CC BY 4.0 for directory, playbook, skills and
   templates require; add licence files, per-folder notes, README section,
   package metadata and contribution terms; keep all third-party notices.
2. **Directory seeding** ([decision 0007](adr/0007-seed-the-directory-from-checkable-sources.md)):
   10 to 20 checked entries, preferring free games whose data can be verified
   locally; look for content no source documents yet. Check each game's licence
   before publishing anything about it ([decision 0004](adr/0004-publish-cases-only-for-free-games.md)).
3. **WAD reader**: a read-only reader for WAD-based engines (levels, lumps,
   textures, sounds, references), tested with self-made data and checked with
   the freely licensed Freedoom data, with its findings shown in the gallery.
   It should only be built if it adds findings the existing tools cannot reach.
