"""Engine gating and the file boundary of browser game sessions.

These tests use dummy engine bytes for HTTP transport only. Actual engine
execution is covered by browser_game_acceptance.py with LibreQuake.
"""
import hashlib
import http.client
import json
import os
import threading
from unittest.mock import patch

from helpers import IsolatedTestCase
from cutcontent.core import service
from cutcontent.core.folders import FolderPermissionError
from cutcontent.core.game_launch import SESSION_LIFETIME_SECONDS, prepare_game_launch
from cutcontent.core.scan_report import save_report
from cutcontent.core.settings import write_json_atomically
from cutcontent.demo import create_demo_game
from cutcontent.platforms.base import PreviewError
from cutcontent.platforms.browser_engines import quake_browser_engine_status
from cutcontent.web.server import make_server


class GameLaunchTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.engine = self.workspace / "engine"
        self.engine.mkdir()
        (self.engine / "engine.js").write_text("// transport fixture", encoding="utf-8")
        (self.engine / "engine.wasm").write_bytes(b"\0asm\x01\0\0\0")
        self.hashes = {name: hashlib.sha256((self.engine / name).read_bytes()).hexdigest() for name in ("engine.js", "engine.wasm")}
        write_json_atomically(self.engine / "build.json", {"bridge_version": 1, "files": self.hashes})
        os.environ["CUT_CONTENT_QWASM_DIR"] = str(self.engine)
        self.game = create_demo_game()
        # Only transport is tested: these additional files need no engine content.
        for name in ("gfx.wad", "gfx/colormap.lmp"):
            target = self.game / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture")
        self.report = service.scan_path(self.game)
        self.level = next(item for item in self.report.items if item.name == "maps/start.bsp")

    def verify_engine(self):
        write_json_atomically(self.engine / "browser-verification.json", {"passed": True, "files": self.hashes})

    def test_unverified_build_stays_disabled_and_changes_invalidate_verification(self):
        self.assertFalse(quake_browser_engine_status()["available"])
        with self.assertRaisesRegex(PreviewError, "browser test"):
            prepare_game_launch(self.report.build_id, self.level.to_dict()["id"])
        self.verify_engine()
        self.assertTrue(quake_browser_engine_status()["available"])
        (self.engine / "engine.js").write_text("changed", encoding="utf-8")
        self.assertFalse(quake_browser_engine_status()["available"])

    def test_only_safe_existing_level_names_can_be_launched(self):
        self.verify_engine()
        level_id = self.level.to_dict()["id"]
        for path in ("maps/start;quit.bsp", "maps/../../outside.bsp", "maps/start\nquit.bsp"):
            with self.subTest(path=path):
                self.level.reference["path"] = path
                save_report(self.report)
                with self.assertRaises(PreviewError):
                    prepare_game_launch(self.report.build_id, level_id)

    def test_session_contains_game_data_but_no_host_directory_access(self):
        self.verify_engine()
        launch = prepare_game_launch(self.report.build_id, self.level.to_dict()["id"])
        self.assertEqual(launch.level_name, "start")
        self.assertEqual(launch.read_game_file(0)[:4], b"PACK")
        self.assertNotIn("path", launch.manifest()["files"][0])
        with self.assertRaises(PreviewError):
            launch.read_engine_file("../build.json")
        with self.assertRaises(PreviewError):
            launch.read_game_file(-1)
        launch.created_at -= SESSION_LIFETIME_SECONDS + 1
        with self.assertRaisesRegex(PreviewError, "expired"):
            launch.manifest()

    def test_revoked_folder_and_replaced_file_are_rechecked(self):
        self.verify_engine()
        launch = prepare_game_launch(self.report.build_id, self.level.to_dict()["id"])
        pak = launch.files[0][1]
        outside = self.workspace / "outside.pak"
        outside.write_bytes(b"private")
        pak.unlink()
        pak.symlink_to(outside)
        with self.assertRaises((FolderPermissionError, PreviewError)):
            launch.read_game_file(0)

    def test_game_size_limit_is_checked_before_serving(self):
        self.verify_engine()
        with patch("cutcontent.core.game_launch.MAXIMUM_GAME_BYTES", 10):
            with self.assertRaisesRegex(PreviewError, "browser limit"):
                prepare_game_launch(self.report.build_id, self.level.to_dict()["id"])

    def test_http_launch_needs_token_and_serves_only_session_resources(self):
        self.verify_engine()
        server, state = make_server(18780)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def request(method, path, token=True):
            connection = http.client.HTTPConnection("127.0.0.1", state.port, timeout=30)
            connection.request(method, path, headers={"X-CutContent-Token": state.token} if token else {})
            response = connection.getresponse()
            result = response.status, dict(response.getheaders()), response.read()
            connection.close()
            return result
        try:
            route = f"/api/game-launch/{self.report.build_id}/{self.level.to_dict()['id']}"
            self.assertEqual(request("POST", route, token=False)[0], 401)
            code, _, payload = request("POST", route)
            self.assertEqual(code, 200, payload)
            root = json.loads(payload)["url"].removesuffix("index.html")
            code, headers, _ = request("GET", root + "index.html", token=False)
            self.assertEqual(code, 200)
            self.assertIn("'wasm-unsafe-eval'", headers["Content-Security-Policy"])
            self.assertEqual(request("GET", root + "engine.wasm", token=False)[0], 200)
            self.assertEqual(request("GET", root + "../build.json", token=False)[0], 404)
            self.assertEqual(request("GET", "/play/unknown/manifest.json", token=False)[0], 404)
            # Removing the folder permission affects already-issued session URLs too.
            with patch("cutcontent.core.folders.allowed_folders", return_value=[]):
                self.assertEqual(request("GET", root + "manifest.json", token=False)[0], 403)
        finally:
            server.shutdown()
            server.server_close()
