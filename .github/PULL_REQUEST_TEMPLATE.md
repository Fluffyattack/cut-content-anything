## Game and build

- Game:
- Build identity (version, region, SHA-256; no paths):
- Platform and engine:

## What this adds or changes

- [ ] Directory entry (`data/directory.json` + regenerated `DIRECTORY.md`)
- [ ] Write-up (`games/<slug>/README.md`)
- [ ] Reader or decoder (with self-made test data)
- [ ] Playbook or skill change

## Evidence

For each item: the four statements (present / possibly unused / loaded under
test / reachable in normal play), release history with sources, and the
quality level. Paste the summary of the runtime test that actually ran.

## Checks

- [ ] `python3 -m unittest discover -s tests -t tests` passed
- [ ] `python3 scripts/check_publication.py` passed
- [ ] No game files, extracted assets, saves, proprietary screenshots or private details
- [ ] Every source was opened; quality levels are honest
- [ ] Owner reviewed this diff (owner ticks this)
