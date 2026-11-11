---
name: cutcontent-triage
description: First phase of a cut-content investigation. Identify the exact local game build (hashes, version, platform, engine, archive formats), check the shared directory and earlier write-ups for documented content, and choose between verifying known claims and discovering from zero.
---

# Triage: which build, which engine, what is already known

Run this before any other investigation work. Read `AGENTS.md` first if you have
not done so in this session.

## Steps

1. **Keep the question.** Write the owner's original question into the case
   notes verbatim. Later phases test it; they never replace it.
2. **Find the build.** `cutcontent list --json` shows discovered builds in the
   allowed folders. Use install metadata and file names to pick the intended
   one. Ask the owner only if two plausible builds would lead to different work.
3. **Record the identity** before reading any write-up: title, region, version
   or revision, platform, SHA-256 of the image or of the main executable and
   largest archives, and the store or medium if known. `cutcontent scan PATH`
   records the format detection; `cutcontent directory match BUILD_ID` hashes
   the build and lists entries that document the same title or exact files.
4. **Identify the engine and formats from bytes**, not from the title: magic
   numbers, archive headers, executable imports, known file tables. See
   `playbook/engine-families.md` for where content usually hides per engine.
5. **Check prior work:** `cutcontent directory search "TITLE"`, the matching
   `games/<slug>/README.md`, and open issues or pull requests for the game.
6. **Choose the path:**
   - *Verify what is documented* when the directory or public sources already
     name candidates. Each claim becomes a hypothesis for this exact build.
   - *Discover from zero* when nothing is documented or the question asks for
     something new.
   Both paths finish with the same runtime and release-history checks.
7. **Note the expected blockers** early: encrypted partitions, missing decoders,
   no lawful runtime available. Protection is never circumvented; record the
   coverage it leaves.

## Output

A short triage record in the private case notes: question, build identity,
engine and formats with evidence, directory matches with their match reason,
chosen path, and the next phase (`cutcontent-research`).

A directory match by title alone is a candidate. Compare the exact build
identity before relying on an entry.
