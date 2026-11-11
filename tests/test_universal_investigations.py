"""Question/provenance boundaries; real-game behavior is tested separately."""
import base64
import json
import struct

from helpers import IsolatedTestCase
from cutcontent.core import service
from cutcontent.core.content_search import create_investigation, search_report
from cutcontent.core.decoded_scenes import export_existing_scene, register_decoded_scene, validate_scene
from cutcontent.core.release_history import record_release_history
from cutcontent.core.scan_report import list_reports, load_report, record_evidence
from cutcontent.demo import create_demo_game


class UniversalInvestigationTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.game = create_demo_game()
        self.report = service.scan_path(self.game)
        self.build_id = self.report.build_id
        self.map_item = next(item for item in self.report.items if item.kind == "map" and item.name == "maps/start.bsp")

    def test_question_and_kind_search_keep_unflagged_candidates(self):
        report = load_report(self.build_id)
        result = search_report(report, [], ["map"])
        self.assertIn(self.map_item.item_id, [item["item_id"] for item in result["candidates"]])
        question = "Find a map with a different internal name; investigate its real origin."
        case = create_investigation(self.build_id, question, [], ["map"])
        self.assertEqual(case["investigation"]["question"], question)
        self.assertEqual(case["investigation"]["status"], "investigating")

    def export_scene(self):
        package = self.workspace / "actual-demo-map.scene.json"
        export_existing_scene(self.build_id, self.map_item.item_id, package, [self.game / "pak0.pak"])
        return package

    def test_shared_scene_keeps_source_item_and_rechecks_original_bytes(self):
        package = self.export_scene()
        registered = register_decoded_scene(self.build_id, self.map_item.item_id, package)
        self.assertGreater(registered["triangles"], 0)
        viewed = json.loads(service.preview_item(self.build_id, self.map_item.item_id).body)
        self.assertGreater(len(viewed["groups"]), 0)
        with (self.game / "pak0.pak").open("ab") as handle:
            handle.write(b"changed original")
        with self.assertRaisesRegex(ValueError, "source bytes"):
            service.preview_item(self.build_id, self.map_item.item_id)

    def test_scene_rejects_nan_and_mismatched_vertex_arrays(self):
        package = json.loads(self.export_scene().read_text())
        scene = package["scene"]
        scene["groups"][0]["positions"] = base64.b64encode(struct.pack("<9f", float("nan"), *([0.] * 8))).decode()
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_scene(scene)
        scene = json.loads(self.export_scene_copy().read_text())["scene"]
        scene["groups"][0]["uv"] = ""
        with self.assertRaisesRegex(ValueError, "matching"):
            validate_scene(scene)

    def export_scene_copy(self):
        path = self.workspace / "second-actual-demo-map.scene.json"
        export_existing_scene(self.build_id, self.map_item.item_id, path, [self.game / "pak0.pak"])
        return path

    def test_source_history_survives_rescan_without_changing_runtime_evidence(self):
        before = load_report(self.build_id)
        original = next(item for item in before["items"] if item["id"] == self.map_item.item_id)
        with self.assertRaisesRegex(ValueError, "public sources"):
            record_release_history(self.build_id, self.map_item.item_id, "unreleased_confirmed", "Fixture classification", [])
        record_release_history(self.build_id, self.map_item.item_id, "released", "Unit fixture: generated test data only.",
                               ["https://example.org/unit-fixture-source"], "asset_distribution")
        service.scan_path(self.game)
        after = next(item for item in load_report(self.build_id)["items"] if item["id"] == self.map_item.item_id)
        self.assertEqual(after["release_history"]["status"], "released")
        self.assertEqual(after["evidence"], original["evidence"])

    def test_subscene_does_not_inherit_parent_use_or_runtime_claims(self):
        package_path = self.export_scene()
        package = json.loads(package_path.read_text())
        generic = service.scan_path(self.game, "generic_folder")
        parent = next(item for item in generic.items if item.name == "pak0.pak")
        record_evidence(generic.build_id, parent.item_id, "possibly_unused", "no", "Unit fixture: the container is referenced.", "static")
        package["item_id"] = parent.item_id
        package["scene_name"] = "maps/start.bsp"
        package_path.write_text(json.dumps(package))
        before_summary = next(report for report in list_reports() if report["build_id"] == generic.build_id)
        registration = register_decoded_scene(generic.build_id, parent.item_id, package_path)
        report = load_report(generic.build_id)
        child = next(item for item in report["items"] if item["id"] == registration["item_id"])
        parent_after = next(item for item in report["items"] if item["id"] == parent.item_id)
        self.assertNotEqual(child["id"], parent.item_id)
        self.assertEqual(parent_after["kind"], "file")
        self.assertEqual(parent_after["evidence"]["possibly_unused"]["status"], "no")
        self.assertEqual(child["evidence"]["possibly_unused"]["status"], "unknown")
        self.assertEqual(child["evidence"]["loaded_under_test"]["status"], "not_checked")
        after_summary = next(report for report in list_reports() if report["build_id"] == generic.build_id)
        self.assertEqual(after_summary["statistics"]["items"], before_summary["statistics"]["items"] + 1)
        service.scan_path(self.game, "generic_folder")
        rescanned_summary = next(report for report in list_reports() if report["build_id"] == generic.build_id)
        self.assertEqual(rescanned_summary["statistics"]["items"], after_summary["statistics"]["items"])
        self.assertTrue(any(item["id"] == child["id"] for item in load_report(generic.build_id)["items"]))

    def test_unknown_selected_file_has_explicit_undecoded_coverage(self):
        path = self.workspace / "unknown-resource.container"
        path.write_bytes(b"NOT-A-KNOWN-FORMAT\x00" + b"\x01" * 100)
        report = service.scan_path(path)
        self.assertEqual(report.adapter, "generic_artifact")
        self.assertFalse(report.items[0].details["decoded"])
        self.assertEqual(report.items[0].evidence["loaded_under_test"].status, "not_checked")
