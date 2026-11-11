# Notes for Claude Code

See `AGENTS.md` for the shared rules and the phase map. The skills are synced
copies of `skills/` in `.claude/skills/`; start with `/cut-content-anything`,
which routes to the phase skills (`cutcontent-triage`, `cutcontent-research`,
`cutcontent-decoder`, `cutcontent-reference-analysis`,
`cutcontent-developer-menus`, `cutcontent-runtime-verification`,
`cutcontent-release-history`, `cutcontent-contribute`).

The project's MCP server starts from `.mcp.json` (`python -m cutcontent mcp`).

Quick commands:

- `bin/cutcontent doctor` - setup check
- `bin/cutcontent scan <path>` - scan a game, ROM or disc image (read-only)
- `bin/cutcontent directory match <build-id>` - documented content for a scanned build
- `bin/cutcontent gui` - web gallery on 127.0.0.1
- `python3 -m unittest discover -s tests -t tests` - test suite
- `python3 scripts/check_publication.py` - check before any push
