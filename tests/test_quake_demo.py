"""The Quake adapter against the self-made demo game: every planted case must be found."""

import json
import unittest

from helpers import IsolatedTestCase

from cutcontent.core import service
from cutcontent.core.scan_report import load_report
from cutcontent.demo import create_demo_game
from cutcontent.demo.quake_demo_builder import build_start_level
from cutcontent.formats import quake_bsp, quake_model, quake_pak
from cutcontent.core.byte_sources import MemoryByteSource


class QuakeDemoTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.game_directory = create_demo_game(self.workspace / "demo")
        self.report = load_report(service.scan_path(self.game_directory).build_id)
        self.items = self.items_by_name(self.report)

    def test_report_describes_the_build(self):
        self.assertEqual(self.report["adapter"], "quake")
        self.assertEqual(self.report["title"], "Cut Content Anything demo")
        self.assertFalse(self.report["game_launch"]["available"])
        self.assertIn("missing engine resources", self.report["game_launch"]["reason"])

    def test_allowed_folder_can_be_the_game_directory_itself(self):
        from cutcontent.core.folders import AllowedFolder
        builds = service.discover_builds([AllowedFolder(self.game_directory, "test", True, True)])
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0]["build_id"], self.report["build_id"])

    def test_unreferenced_level_does_not_claim_exhaustive_normal_play_knowledge(self):
        vault = self.items["maps/vault.bsp"]
        self.assertEqual(vault["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(vault["evidence"]["reachable_in_normal_play"]["status"], "unknown")
        self.assertEqual(vault["details"]["normal_access_search"]["status"], "not_found")
        hall = self.items["maps/hall.bsp"]
        self.assertEqual(hall["evidence"]["reachable_in_normal_play"]["status"], "likely")
        self.assertIn("start → hall", hall["evidence"]["reachable_in_normal_play"]["basis"])

    def test_unreferenced_model_and_sound(self):
        self.assertEqual(self.items["progs/cut_robot.mdl"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(self.items["sound/demo/unused_jingle.wav"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(self.items["progs/guard.mdl"]["evidence"]["possibly_unused"]["status"], "no")
        self.assertEqual(self.items["sound/demo/beep.wav"]["evidence"]["possibly_unused"]["status"], "no")

    def test_overridden_file(self):
        older = self.items["progs/guard.mdl (older copy in pak0.pak)"]
        self.assertEqual(older["evidence"]["reachable_in_normal_play"]["status"], "no")
        self.assertEqual(older["location"]["container"], "pak0.pak")

    def test_entities_that_never_appear(self):
        names = set(self.items)
        self.assertIn("item_crate #6 in start", names)  # all spawn flags set
        self.assertIn("monster_removed_prototype #7 in start", names)  # no spawn function
        self.assertIn("monster_guard #8 in start", names)  # inside the pillar
        self.assertIn("Entity type monster_scout", names)  # spawn function no level uses
        self.assertNotIn("monster_guard #4 in start", names)

    def test_unused_embedded_texture(self):
        texture = self.items["demo_old_sign"]
        self.assertEqual(texture["evidence"]["possibly_unused"]["status"], "yes")
        self.assertNotIn("trigger", [name for name, item in self.items.items() if item["is_finding"]])

    def test_every_item_keeps_four_separate_evidence_levels(self):
        for item in self.report["items"]:
            self.assertEqual(set(item["evidence"]), {"present_in_data", "possibly_unused", "loaded_under_test", "reachable_in_normal_play"})
            self.assertEqual(item["evidence"]["loaded_under_test"]["status"], "not_checked")
            self.assertTrue(item["location"])

    def test_level_preview_has_geometry_textures_and_light(self):
        level_item = self.items["maps/start.bsp"]
        result = service.preview_item(self.report["build_id"], level_item["id"], enforce_allowed_folders=False)
        preview = json.loads(result.body)
        self.assertGreater(preview["statistics"]["triangles"], 20)
        self.assertTrue(all(texture["image"].startswith("data:image/png;base64,") for texture in preview["textures"]))
        self.assertNotIn("trigger", [texture["name"] for texture in preview["textures"]])
        self.assertEqual(preview["spawn"]["angle"], 0.0)
        self.assertTrue(preview["lightmap"]["image"].startswith("data:image/png"))
        self.assertEqual(preview["collision"]["hull"], 1)

    def test_player_collision_hull(self):
        level = quake_bsp.read_level(build_start_level())
        self.assertEqual(level.hull_contents(1, (-250, 0, 24)), quake_bsp.CONTENTS_EMPTY)  # player start
        self.assertEqual(level.hull_contents(1, (-40, 0, 24)), quake_bsp.CONTENTS_SOLID)  # touching the pillar
        self.assertEqual(level.hull_contents(1, (-50, 0, 24)), quake_bsp.CONTENTS_EMPTY)
        self.assertEqual(level.hull_contents(1, (-250, 0, 23)), quake_bsp.CONTENTS_SOLID)  # feet in the floor

    def test_model_preview_has_frames_and_animations(self):
        model_item = self.items["progs/cut_robot.mdl"]
        preview = json.loads(service.preview_item(self.report["build_id"], model_item["id"], enforce_allowed_folders=False).body)
        names = [animation["name"] for animation in preview["animations"]]
        self.assertEqual(names, ["idle", "scuttle", "attack"])
        self.assertEqual(len(preview["frames"]), 15)
        thumbnail = service.preview_item(self.report["build_id"], model_item["id"], {"thumbnail": True}, enforce_allowed_folders=False)
        self.assertEqual(thumbnail.content_type, "image/png")

    def test_entity_preview_opens_its_level(self):
        entity = self.items["monster_guard #8 in start"]
        result = service.preview_item(self.report["build_id"], entity["id"], enforce_allowed_folders=False)
        self.assertEqual(result.content_type, "application/json")

    def test_sound_preview_is_wav(self):
        sound = self.items["sound/demo/beep.wav"]
        result = service.preview_item(self.report["build_id"], sound["id"], enforce_allowed_folders=False)
        self.assertEqual(result.body[:4], b"RIFF")

    def test_level_text_preview(self):
        vault_text = self.items["Text in maps/vault.bsp (1 messages)"]
        self.assertTrue(vault_text["is_finding"])
        result = service.preview_item(self.report["build_id"], vault_text["id"], enforce_allowed_folders=False)
        self.assertIn("Unfinished vault (never linked)", result.body.decode("utf-8"))
        self.assertFalse(self.items["Text in maps/start.bsp (1 messages)"]["is_finding"])

    def test_point_contents(self):
        level = quake_bsp.read_level(build_start_level())
        self.assertEqual(level.point_contents((-200, 0, 50)), quake_bsp.CONTENTS_EMPTY)
        self.assertEqual(level.point_contents((0, 0, 50)), quake_bsp.CONTENTS_SOLID)  # pillar
        self.assertEqual(level.point_contents((0, 0, 500)), quake_bsp.CONTENTS_SOLID)  # above the room

    def test_pak_round_trip(self):
        data = quake_pak.build_pak([("a/b.txt", b"hello"), ("c.bin", b"\x00\x01")])
        entries = quake_pak.read_pak_directory(MemoryByteSource(data))
        self.assertEqual([(entry.name, entry.size) for entry in entries], [("a/b.txt", 5), ("c.bin", 2)])
        with self.assertRaises(quake_pak.PakFormatError):
            quake_pak.read_pak_directory(MemoryByteSource(b"NOPE" + bytes(20)))

    def test_damaged_model_is_refused(self):
        with self.assertRaises(quake_model.ModelFormatError):
            quake_model.read_model(b"IDPO" + bytes(10))

    def test_recorded_runtime_evidence_survives_a_new_scan(self):
        from cutcontent.core.scan_report import record_evidence

        vault = self.items["maps/vault.bsp"]
        record_evidence(self.report["build_id"], vault["id"], "loaded_under_test", "yes", "Loaded with 'map vault' in a test engine.", "runtime")
        service.scan_path(self.game_directory)
        reloaded = self.items_by_name(load_report(self.report["build_id"]))
        self.assertEqual(reloaded["maps/vault.bsp"]["evidence"]["loaded_under_test"]["status"], "yes")
        self.assertEqual(reloaded["maps/vault.bsp"]["evidence"]["loaded_under_test"]["method"], "runtime")

    def test_investigation_tasks_for_both_clients(self):
        vault = self.items["maps/vault.bsp"]
        claude = service.investigation_task(self.report["build_id"], "claude", [vault["id"]])
        codex = service.investigation_task(self.report["build_id"], "codex", [vault["id"]])
        self.assertIn(".claude/skills/cut-content-anything", claude)
        self.assertIn(".agents/skills/cut-content-anything", codex)
        for text in (claude, codex):
            self.assertIn("maps/vault.bsp", text)
            self.assertIn("Loaded under test conditions", text)
            self.assertIn("no DRM", text)
            self.assertIn("sound tests and test rooms", text)
            self.assertIn("Load every map reported as a finding", text)
            self.assertIn("exact source file hash", text)


if __name__ == "__main__":
    unittest.main()
