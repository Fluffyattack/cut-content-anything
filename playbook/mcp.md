# The MCP server

The Model Context Protocol (MCP) lets coding agents call local tools. This
project's server runs on standard input and output and needs only Python.

```sh
cutcontent mcp            # or: python -m cutcontent mcp
```

Inside this checkout, Claude Code reads the server definition from `.mcp.json`. Elsewhere, register it once:

```sh
claude mcp add cut-content-anything -- python -m cutcontent mcp      # Claude Code, user scope
codex mcp add cut-content-anything -- python -m cutcontent mcp       # Codex
```

Run these inside the checkout, or install the package first (`pipx install .`)
and use `cutcontent mcp` as the command.

## Tools

| Tool | What it does |
| --- | --- |
| `search_directory` | Search documented content by words, kind and quality level |
| `validate_directory_entry` | Check a proposed entry against the schema and evidence rules |
| `list_local_builds` | List discovered local builds and whether they were scanned |
| `detect_game` | Detect the platform and format of a path inside an allowed folder |
| `match_build_to_directory` | Hash a scanned build and list matching directory entries |
| `search_build` | Search a scanned build's inventory and decoded text |
| `list_guides`, `read_guide` | Read AGENTS.md, playbook pages, skills, templates and write-ups |

All tools are read-only. Paths outside the owner's allowed folders are refused.

Questions about executable code need a second server for binary analysis, for example REA:
this server knows the workflow and the evidence rules, REA looks inside the executable.
