"""The MCP server, driven by a real client session over standard input and output."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from helpers import IsolatedTestCase

from cutcontent.core import service
from cutcontent.demo import create_demo_game

ROOT = Path(__file__).resolve().parents[1]


class McpSession:
    """A minimal MCP client: starts `python -m cutcontent mcp` and exchanges JSON-RPC lines."""

    def __init__(self):
        self.process = subprocess.Popen([sys.executable, "-m", "cutcontent", "mcp"], cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.next_identifier = 1

    def request(self, method: str, params: dict | None = None) -> dict:
        identifier = self.next_identifier
        self.next_identifier += 1
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params or {}}) + "\n")
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        assert response["id"] == identifier, response
        return response

    def notify(self, method: str) -> None:
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def call(self, tool: str, arguments: dict) -> tuple[bool, str]:
        result = self.request("tools/call", {"name": tool, "arguments": arguments})["result"]
        return result["isError"], result["content"][0]["text"]

    def close(self) -> int:
        self.process.stdin.close()
        code = self.process.wait(timeout=30)
        self.process.stdout.close()
        self.process.stderr.close()
        return code


class McpServerTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.session = McpSession()

    def tearDown(self):
        if self.session.process.poll() is None:
            self.session.close()
        super().tearDown()

    def test_handshake_and_tool_list(self):
        initialised = self.session.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                           "clientInfo": {"name": "test", "version": "1"}})["result"]
        self.assertEqual(initialised["serverInfo"]["name"], "cut-content-anything")
        self.assertIn("tools", initialised["capabilities"])
        self.session.notify("notifications/initialized")
        tools = {tool["name"] for tool in self.session.request("tools/list")["result"]["tools"]}
        self.assertEqual(tools, {"search_directory", "validate_directory_entry", "list_local_builds", "detect_game",
                                 "match_build_to_directory", "search_build", "list_guides", "read_guide"})
        self.assertEqual(self.session.request("unknown/method")["error"]["code"], -32601)
        self.assertEqual(self.session.close(), 0)

    def test_directory_and_guides(self):
        self.session.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        failed, text = self.session.call("search_directory", {"query": "librequake dev"})
        self.assertFalse(failed)
        self.assertIn("maps/dev.bsp", json.loads(text)["entries"][0]["item"])
        failed, text = self.session.call("validate_directory_entry", {"entry": {"game": "x"}})
        self.assertFalse(json.loads(text)["valid"])
        failed, text = self.session.call("list_guides", {})
        guides = json.loads(text)["guides"]
        self.assertIn("AGENTS.md", guides)
        self.assertIn("playbook/triage.md", guides)
        self.assertIn("skills/cutcontent-triage/SKILL.md", guides)
        failed, text = self.session.call("read_guide", {"name": "playbook/triage.md"})
        self.assertTrue(text.startswith("# Triage"))
        failed, text = self.session.call("read_guide", {"name": "../outside.md"})
        self.assertTrue(failed)

    def test_local_build_tools_on_a_scanned_demo_game(self):
        game = create_demo_game()
        build_id = service.scan_path(game).build_id
        service.discover_builds()
        self.session.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        failed, text = self.session.call("list_local_builds", {"query": "demo"})
        self.assertFalse(failed, text)
        self.assertIn(build_id, [build["build_id"] for build in json.loads(text)["builds"]])
        failed, text = self.session.call("detect_game", {"path": str(game)})
        self.assertFalse(failed, text)
        self.assertEqual(json.loads(text)["detections"][0]["adapter"], "quake")
        failed, text = self.session.call("detect_game", {"path": str(self.workspace)})
        self.assertTrue(failed, "paths outside the allowed folders must be refused")
        failed, text = self.session.call("match_build_to_directory", {"build_id": build_id})
        self.assertFalse(failed, text)
        self.assertGreater(json.loads(text)["files_hashed"], 0)
        failed, text = self.session.call("search_build", {"build_id": build_id, "terms": ["unused_jingle"]})
        self.assertFalse(failed, text)
        self.assertGreater(json.loads(text)["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
