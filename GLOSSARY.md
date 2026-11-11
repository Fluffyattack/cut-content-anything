# Cut Content Investigation

These terms describe an investigation of locally owned game data and the evidence
needed to support its conclusions.

## Investigation

**Investigation question**:
A free-form claim or question about content in one local game build that the skill
tests against source data, public research and observed behavior.
_Avoid_: Platform task, format task

**Candidate build**:
A local game file or folder selected for investigation. Being a candidate says
nothing about whether its contents can be decoded or the game can be started.
_Avoid_: Supported game, playable game

**Completed investigation**:
An investigation whose question has been answered with stated data coverage,
public-source research, a documented search for developer functions and an
actual operated start of the exact game build. Every map reported as a finding
must also be loaded in the actual game. A case with an unresolved game or map
load remains open, even when its static data findings are useful.
_Avoid_: Completed scan

**Finding**:
A specific piece of content tied to a location in the candidate build, with
separate statements about presence, possible non-use, runtime loading and normal-play reachability.
_Avoid_: Cut content, unreleased content (unless separately established)

**Verified playable build**:
A build whose exact file identity was recorded and whose real game runtime was
started, operated and observed under stated test conditions.
_Avoid_: Recognised build, scanned build

## Evidence and output

**Scan**:
A read-only inventory and analysis of source data. A scan is evidence about the
data it covered, not evidence that the game ran.
_Avoid_: Gameplay test

**Preview**:
A local rendering or playback of decoded data in the gallery. A preview is not
an observation of the game loading that content.
_Avoid_: Game start

**Runtime observation**:
An executed action in the actual game, engine or emulator, with recorded input,
conditions and output. It supports only the behavior that was observed.
_Avoid_: Static inference

**Isolated test copy**:
A private copy of a legally supplied build that may be changed solely to test
whether content loads in the actual game. The original remains read-only; the
record identifies the change and does not imply normal-play reachability.
_Avoid_: Modified original

**Private case**:
The local record of one investigation, including source locations, reports,
screenshots and saves. General methods and readers can be shared without publishing the case.
_Avoid_: Public example by default
