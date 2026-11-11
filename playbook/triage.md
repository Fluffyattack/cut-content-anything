# Triage

Goal: know exactly which build you are looking at, what it is made of and what
others already found, before reading a single write-up.

## 1. The build

| Record | How |
| --- | --- |
| Title, region, version or revision | Header fields (cartridge header, disc parameter file, executable version resource), install metadata, title screen |
| Identity | SHA-256 of the image; for installed PC games the main executable and the largest archives. `cutcontent directory match BUILD` hashes a scanned build. |
| Platform and medium | Cartridge, disc, digital store, source port |
| Engine | From bytes: archive magic numbers, executable imports and strings, known file tables |

Two builds with the same title are different builds until their hashes match.
Revisions, regional releases and later ports often add, remove or restore content.

## 2. Formats

`cutcontent scan PATH` detects the container family and lists what the built-in
readers cover. `cutcontent formats` shows the support level of every reader.
Anything listed as detection-only is a decoder task, not an empty result.

## 3. Prior work

- `cutcontent directory search "TITLE"` and `cutcontent directory match BUILD`.
- `games/<slug>/README.md` if it exists.
- Open issues and pull requests mentioning the game.

## 4. Choose the path

| | Verify what is documented | Discover from zero |
| --- | --- | --- |
| When | The directory or public sources already name candidates | Nothing documented, or the question asks for something new |
| First step | Turn each claim into a hypothesis for this exact build | Inventory, reference analysis and decoding |
| Typical outcome | Upgraded quality level, corrected entry, build-specific differences | New entries, new readers, new write-up |

Both paths end with developer-function search, runtime verification and
release history.

## 5. Stop conditions

Stop and tell the owner if the build is not what they meant, if the data is
encrypted beyond what can be read lawfully, or if the evidence contradicts this
playbook. Propose a playbook fix in that case.
