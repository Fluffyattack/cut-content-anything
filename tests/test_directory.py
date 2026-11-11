"""The shared directory: validation rules, search, build matching and the generated page."""

import contextlib
import copy
import io
import hashlib
import json
import unittest

from helpers import IsolatedTestCase

from cutcontent import directory
from cutcontent.cli import main
from cutcontent.core import service
from cutcontent.core.scan_report import load_report
from cutcontent.demo import create_demo_game

VALID_ENTRY = {
    "game": "Example Game",
    "platforms": ["PC"],
    "engine": "unknown",
    "item": "maps/secret.bsp",
    "kind": "map",
    "summary": "A self-made test entry.",
    "match": {"titles": ["Example Game"], "codes": ["EXMP"], "sha256": []},
    "builds": [{"label": "1.0", "identity": "sha256:" + "0" * 64}],
    "evidence": {
        "present_in_data": {"answer": "yes", "basis": "Stored in pak0.pak."},
        "possibly_unused": {"answer": "unknown", "basis": ""},
        "loaded_under_test": {"answer": "unknown", "basis": ""},
        "reachable_in_normal_play": {"answer": "unknown", "basis": ""},
    },
    "release": {"status": "unknown", "basis": ""},
    "quality": "data-verified",
    "sources": ["https://example.org/source"],
    "checked": "2026-11-11",
}


class DirectoryValidationTest(unittest.TestCase):
    def test_a_complete_entry_is_valid(self):
        self.assertEqual(directory.validate_entry(copy.deepcopy(VALID_ENTRY)), [])

    def broken(self, change) -> list[str]:
        entry = copy.deepcopy(VALID_ENTRY)
        change(entry)
        return directory.validate_entry(entry)

    def test_rules_are_enforced(self):
        cases = {
            "missing field 'sources'": lambda entry: entry.pop("sources"),
            "kind 'cutscene'": lambda entry: entry.update(kind="cutscene"),
            "requires present_in_data = yes": lambda entry: entry["evidence"]["present_in_data"].update(answer="unknown"),
            "requires loaded_under_test = yes": lambda entry: entry.update(quality="runtime-verified"),
            "requires at least one identified build": lambda entry: entry.update(builds=[]),
            "gives no basis": lambda entry: entry["evidence"]["possibly_unused"].update(answer="yes"),
            "release.scope must be one of": lambda entry: entry["release"].update(status="released", basis="archive"),
            "https:// links": lambda entry: entry.update(sources=["http://example.org"]),
            "not a real date": lambda entry: entry.update(checked="2026-02-30"),
            "does not exist": lambda entry: entry.update(write_up="games/nothing/README.md"),
        }
        for expected, change in cases.items():
            problems = self.broken(change)
            self.assertTrue(any(expected in problem for problem in problems), f"{expected}: {problems}")

    def test_duplicates_are_reported(self):
        problems = directory.validate_entries([copy.deepcopy(VALID_ENTRY), copy.deepcopy(VALID_ENTRY)])
        self.assertTrue(any("duplicate" in problem for problem in problems))

    def test_published_directory_is_valid_and_generated(self):
        entries = directory.load_entries()
        self.assertEqual(directory.validate_entries(entries), [])
        self.assertEqual(directory.render_markdown(entries), directory.DIRECTORY_PAGE.read_text(encoding="utf-8"))


class DirectorySearchAndMatchTest(IsolatedTestCase):
    def test_search_needs_every_word_and_honours_filters(self):
        entries = [copy.deepcopy(VALID_ENTRY)]
        self.assertEqual(len(directory.search_entries(entries, "example secret")), 1)
        self.assertEqual(directory.search_entries(entries, "example missing"), [])
        self.assertEqual(directory.search_entries(entries, "", kind="audio"), [])
        self.assertEqual(directory.search_entries(entries, "", quality="data-verified")[0]["id"], "example-game/maps-secret-bsp")

    def test_build_matching_prefers_hashes_then_codes_then_titles(self):
        entry = copy.deepcopy(VALID_ENTRY)
        entry["match"]["sha256"] = ["ab" * 32]
        by_hash = directory.match_build([entry], {"title": "Other", "build_label": "x", "sha256": ["AB" * 32]})
        self.assertEqual(by_hash[0]["match_reason"], "same SHA-256")
        by_code = directory.match_build([entry], {"title": "Other", "build_label": "other.nds, EXMP, revision 0", "sha256": []})
        self.assertEqual(by_code[0]["match_reason"], "same product code")
        by_title = directory.match_build([entry], {"title": "EXAMPLE GAME", "build_label": "", "sha256": []})
        self.assertIn("same title", by_title[0]["match_reason"])
        self.assertEqual(directory.match_build([entry], {"title": "Unrelated", "build_label": "", "sha256": []}), [])
        prefixed = dict(copy.deepcopy(VALID_ENTRY), game="Quake", match={"titles": ["Quake"], "codes": [], "sha256": []})
        self.assertEqual(directory.match_build([prefixed], {"title": "LibreQuake", "build_label": "id1 folder", "sha256": []}), [],
                         "a title must match whole words, not a part of another title")
        self.assertEqual(len(directory.match_build([prefixed], {"title": "Quake (Shareware)", "build_label": "", "sha256": []})), 1)

    def test_a_scanned_folder_build_is_identified_by_its_archive_hashes(self):
        game = create_demo_game()
        report = load_report(service.scan_path(game).build_id)
        build = directory.build_from_report(report)
        expected = {hashlib.sha256(path.read_bytes()).hexdigest() for path in game.rglob("*.pak")
                    if path.stat().st_size >= directory.IDENTITY_MINIMUM_FILE_BYTES}
        self.assertTrue(expected)
        self.assertTrue(expected <= set(build["sha256"]))
        entry = copy.deepcopy(VALID_ENTRY)
        entry["match"] = {"titles": [], "codes": [], "sha256": sorted(expected)[:1]}
        self.assertEqual(directory.match_build([entry], build)[0]["match_reason"], "same SHA-256")

    def test_command_line_search_validate_and_check(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["directory", "validate"]), 0)
            self.assertEqual(main(["directory", "check"]), 0)
            self.assertEqual(main(["directory", "search", "librequake", "--json"]), 0)
        self.assertIn("maps/dev.bsp", output.getvalue())


if __name__ == "__main__":
    unittest.main()
