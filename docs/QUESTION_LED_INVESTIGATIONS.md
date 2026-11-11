# Investigate a question about a game

The question drives the investigation. The platform reader supplies access to
the data; its current feature list does not define which questions can be asked.
The Claude Code and Codex skill uses the same workflow and gallery.

For example, asking whether one game contains a map from another game starts a
hypothesis. Establish the local build, research the alleged map, inspect actual
containers and references, decode plausible candidates and compare the result.
A similar filename alone does not establish the relationship.

## Start with the actual game

```sh
cutcontent doctor
cutcontent list --json
cutcontent investigate /path/to/game --question "Find a hidden map, show it and research its release history" --kind map --json
cutcontent search BUILD --term test --term prototype --kind map --json
```

`investigate` scans the supplied path (or resolves an unambiguous library title)
and saves the question, initial candidates and search coverage privately. That
is the start of the work. The agent then follows containers, actual references,
decoded contents and relevant public sources. Ordinary unflagged maps remain
valid candidates. `search` reports which supported text previews were actually
read and which previews failed; it does not claim to search undecoded bytes.

An explicitly selected unknown file gets an honest detection-only inventory.
The agent can add a read-only decoder using actual format evidence, validate it
against that file and continue. Encryption and inaccessible parts retain their
actual limits. Original game files stay read-only.

In the gallery, enter the question and use **Copy task: Claude Code** or
**Copy task: Codex**. The copied task preserves the question and selected game.
The agent runs the investigation with its tools, including web search. The
gallery itself does not run an embedded language model or automatically certify
release history.

For every investigated game, the agent also searches available data, shipped
code and public sources for developer/debug menus, level or stage selection,
sound tests and test rooms. Record searched areas and inaccessible areas.
Open and operate any reported function in the actual game. This coverage cannot
establish that no other hidden function exists.

## Show actual decoded maps

Existing map readers open their real geometry directly. A reader developed for
another engine can export the common `cutcontent.scene.v1` package: triangle
positions, texture coordinates, available PNG textures and source provenance.
See the [skill's scene contract](../skills/cut-content-anything/references/question-led-investigations.md).

```sh
cutcontent scene export BUILD MAP_ITEM /private/output/map.scene.json --source-file /path/to/game/archive.pak
cutcontent scene register BUILD MAP_ITEM /private/output/map.scene.json
```

For a map inside a larger archive, register against its parent item and include
the actual internal `scene_name` in the package. Registration returns a separate
map item. The parent remains a file: its use, runtime observations and release
assessment do not become evidence about the child scene.

Source input hashes are checked when registering and opening the scene. The
gallery uses a common orbit/zoom/pan viewer, with scale derived from the actual
bounds. A successful preview establishes decoded display, not successful game
loading, collision, normal-play access or an unreleased status.

Keep converted geometry, proprietary images and decoder work products private
and outside the game and public checkout. The publication check rejects private
scene packages even if their extension is changed.

## Research publication separately

The agent must search the web and open relevant sources. Prefer official release
files, developer statements and first-party version histories. Compare those
claims with the identified local bytes. Community reports can guide further
checks; an empty search is not proof that something was never released.

```sh
cutcontent release set BUILD ITEM released --scope asset_distribution --basis "Actual files matched the official release archive." --source https://example.org/official-release
```

The URL above is an example; use the source actually opened and checked. The
command validates URL syntax and records an assessment. It does not read or
verify the page. The agent is responsible for the source research.

| Scope | Question |
| --- | --- |
| `asset_distribution` | Were these data bytes publicly distributed? |
| `playable_release` | Was this content released as a regular playable experience? |
| `project_release` | Was the game or project itself released? |

Statuses are `unknown`, `unreleased_candidate`, `unreleased_confirmed` and
`released`. Non-unknown assessments need source URLs and a stated basis. The
panel shows the scope, sources and date the assessment was recorded. Rescanning
keeps this assessment separate from the four technical evidence statements.

## Execute the claimed behavior

Open a claimed debug menu and operate it in the actual game. Start a claimed
playable map in the actual engine. A completed investigation starts and operates
the exact game build, and every map reported as a finding must load in that game.
A safe, documented test route may use an isolated copy; it does not establish
normal-play access. If lawful local firmware or another runtime component is
missing, ask whether the owner can supply it. An unresolved game or map load
keeps the case open with its concrete blocker. Verify actual player movement rather than a
camera move or a frame change. For persistence claims, use a fresh private save,
compare before/after values and load it through the regular game UI in a new
process. Retain actual screenshots and reports.

```sh
cutcontent evidence set BUILD ITEM loaded_under_test yes --method runtime --access-route direct_start --basis "Started this exact card in a fresh session and observed actual player movement."
```

Only record that example after actually executing it. Normal-play access needs
its own executed normal route. If the checked exits and references reveal no
route, the precise statement is **No regular access found**, with search
coverage shown. It is not proof that every possible route is absent.

The [LibreQuake dev demo](demos/librequake-dev.md) is an executed example from
finding card to real gameplay, with public evidence and a reproducible test.
