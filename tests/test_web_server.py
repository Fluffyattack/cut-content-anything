"""The local web server: binding, host check, session token, allowed folders, previews."""

import http.client
import json
import re
import threading
import unittest

import fixture_builders as fixtures
from helpers import IsolatedTestCase

from cutcontent.core import folders
from cutcontent.demo import create_demo_game
from cutcontent.web.server import make_server


class WebServerTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        create_demo_game()  # inside the demo folder, which is allowed
        self.outside = fixtures.pc_game_folder(self.workspace)  # not allowed
        self.server, self.state = make_server(18749)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.state.port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def request(self, method, path, body=None, token=True, host=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Host": host or f"127.0.0.1:{self.port}", "Content-Type": "application/json"}
        if token:
            headers["X-CutContent-Token"] = self.state.token
        connection.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, dict(response.getheaders()), data

    def wait_for_job(self, job_id):
        for _ in range(300):
            status, _, data = self.request("GET", f"/api/jobs/{job_id}")
            job = json.loads(data)
            if job["status"] in ("done", "failed"):
                return job
            threading.Event().wait(0.1)
        self.fail("scan did not finish")

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_index_contains_token_and_security_headers(self):
        status, headers, data = self.request("GET", "/", token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.state.token, data.decode("utf-8"))
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_foreign_host_header_is_rejected(self):
        status, _, _ = self.request("GET", "/", token=False, host="evil.example:80")
        self.assertEqual(status, 403)

    def test_api_needs_the_session_token(self):
        status, _, _ = self.request("GET", "/api/overview", token=False)
        self.assertEqual(status, 401)

    def test_scan_outside_allowed_folders_is_refused(self):
        status, _, data = self.request("POST", "/api/scan", {"path": str(self.outside)})
        job = self.wait_for_job(json.loads(data)["job_id"])
        self.assertEqual(job["status"], "failed")
        self.assertIn("not inside an allowed folder", job["error"])

    def test_symbolic_link_out_of_an_allowed_folder_is_refused(self):
        link = folders.demo_folder() / "sneaky-link"
        link.symlink_to(self.outside)
        with self.assertRaises(folders.FolderPermissionError):
            folders.require_inside_allowed_folder(link)

    def test_library_scan_preview_and_task(self):
        status, _, data = self.request("POST", "/api/library", {})
        games = json.loads(data)["games"]
        self.assertEqual([game["title"] for game in games], ["Cut Content Anything demo"])
        build = games[0]["builds"][0]
        status, _, data = self.request("POST", "/api/scan", {"path": build["path"]})
        job = self.wait_for_job(json.loads(data)["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        status, _, data = self.request("GET", f"/api/report/{job['build_id']}")
        report = json.loads(data)
        items = {item["name"]: item for item in report["items"]}

        level = items["maps/start.bsp"]
        status, headers, data = self.request("GET", f"/api/preview/{report['build_id']}/{level['id']}")
        self.assertEqual(status, 200)
        self.assertGreater(json.loads(data)["statistics"]["triangles"], 0)

        sound = items["sound/demo/beep.wav"]
        status, headers, data = self.request("GET", f"/api/preview/{report['build_id']}/{sound['id']}?token={self.state.token}", token=False)
        self.assertEqual((status, data[:4]), (200, b"RIFF"))

        status, _, data = self.request("GET", f"/api/task/{report['build_id']}?client=codex&items={level['id']}")
        self.assertIn("$cut-content-anything", json.loads(data)["text"])

    def test_report_of_a_folder_that_is_no_longer_allowed_is_refused(self):
        from cutcontent.core.service import scan_path

        report = scan_path(self.outside)
        status, _, _ = self.request("GET", f"/api/report/{report.build_id}")
        self.assertEqual(status, 403)

    def test_static_files_cannot_escape(self):
        status, _, _ = self.request("GET", "/static/../server.py", token=False)
        self.assertEqual(status, 404)
        status, headers, _ = self.request("GET", "/static/vendor/three/three.module.js", token=False)
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))


if __name__ == "__main__":
    unittest.main()
