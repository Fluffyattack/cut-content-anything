# Directory entry schema

`data/directory.json` holds every entry; `cutcontent directory build` renders
[DIRECTORY.md](../DIRECTORY.md) from it. Change entries only in the JSON file;
the table is regenerated.
`cutcontent directory validate` checks every rule below, and the test suite
fails if `DIRECTORY.md` is out of date.

One entry describes **one piece of content in one game**. Several builds of the
same game share an entry when the content is the same; list each checked build.

```json
{
  "game": "LibreQuake",
  "platforms": ["PC"],
  "engine": "Quake engine (id Tech 2)",
  "item": "maps/dev.bsp",
  "kind": "map",
  "summary": "One or two plain sentences: what it is and why it is interesting.",
  "internal_names": ["dev"],
  "match": {"titles": ["LibreQuake"], "codes": [], "sha256": ["<sha-256 of an image or archive>"]},
  "builds": [{"label": "v0.09-beta Lite, pak0.pak", "identity": "sha256:<...>"}],
  "evidence": {
    "present_in_data": {"answer": "yes", "basis": "where exactly"},
    "possibly_unused": {"answer": "yes", "basis": "which references were checked"},
    "loaded_under_test": {"answer": "yes", "basis": "what was executed and observed"},
    "reachable_in_normal_play": {"answer": "unknown", "basis": ""}
  },
  "release": {"status": "released", "scope": "asset_distribution", "basis": "why"},
  "quality": "runtime-verified",
  "verified_with_this_project": true,
  "write_up": "games/librequake/README.md",
  "notes": "Anything the next agent should know.",
  "sources": ["https://..."],
  "checked": "2026-11-10"
}
```

## Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `game` | yes | Display title of the game |
| `year` | no | First release year of the game |
| `platforms` | yes | Platforms the entry was checked or reported for |
| `engine` | yes | Engine family, `unknown` if not established |
| `item` | yes | The internal name or path of the content, as stored |
| `kind` | yes | `map`, `level`, `character`, `enemy`, `item`, `weapon`, `model`, `texture`, `audio`, `music`, `text`, `dialogue`, `menu`, `mechanic`, `code` or `other` |
| `summary` | yes | Plain-language description |
| `internal_names` | no | Aliases that help searches |
| `match` | no | How `cutcontent directory match` recognises a local build: title aliases, product codes (cartridge or disc serials), SHA-256 values of images or archives |
| `builds` | for `data-verified` and above | Each checked build with a label and an identity (normally a SHA-256) |
| `evidence` | yes | The four statements, each with `answer` (`yes`, `no`, `unknown`) and a `basis` for every answer other than `unknown` |
| `release` | yes | `status` (`released`, `unreleased_candidate`, `unreleased_confirmed`, `unknown`); `scope` (`asset_distribution`, `playable_release`, `project_release`) and `basis` for every status other than `unknown` |
| `quality` | yes | See below |
| `verified_with_this_project` | no | `true` if the checks were done with this project's tools and skills |
| `write_up` | no | Path to `games/<slug>/README.md`; must exist |
| `notes` | no | Open work, caveats |
| `sources` | yes | At least one `https://` link that was opened and supports the entry |
| `checked` | yes | Date of the last check, `YYYY-MM-DD` |

## Quality levels

| `quality` | Meaning | Required evidence |
| --- | --- | --- |
| `source-reports` | A public source was opened and states it | A source link |
| `data-verified` | The actual bytes or code were located in an identified build | `present_in_data = yes`, at least one build |
| `runtime-verified` | Loaded and observed in the actual game, engine or emulator | additionally `loaded_under_test = yes` |

## Rules

- Do not guess. Unknown is `unknown`.
- A filename such as `test` or `beta` is a lead, never a release claim.
- No game data in the directory: names, paths, sizes and hashes are fine;
  extracted content is not.
- `reachable_in_normal_play = yes` needs an executed normal route; a debug menu
  or direct start is `loaded_under_test`.
