"""The publication check: allowlisted file types only, no private data, no scene packages."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("publication_check", ROOT / "scripts" / "check_publication.py")
publication_check = importlib.util.module_from_spec(specification)
specification.loader.exec_module(publication_check)


class PublicationPrivacyTest(unittest.TestCase):
    def test_only_source_documentation_and_screenshots_are_allowed(self):
        for allowed in ("cutcontent/cli.py", "README.md", "docs/screenshots/gallery.png", "bin/cutcontent", "scripts/qwasm_bridge.c"):
            self.assertIsNone(publication_check.file_type_problem(allowed), allowed)
        for refused in ("game.iso", "image.bin", "dump.zip", "docs/photo.png", "engine.wasm", "save.sav", "unknown.xyz"):
            self.assertIsNotNone(publication_check.file_type_problem(refused), refused)

    def test_private_paths_and_mail_addresses_are_rejected(self):
        private_path = "/" + "home" + "/" + "pi" + "/private-file"  # built at runtime so this file stays clean
        self.assertTrue(publication_check.private_text_problems("notes.txt", private_path.encode()))
        address = "someone" + "@" + "gmail.com"
        self.assertTrue(publication_check.private_text_problems("notes.txt", address.encode()))
        self.assertEqual([], publication_check.private_text_problems("notes.txt", b"nothing private here"))

    def test_decoded_scene_is_private_even_without_home_paths(self):
        package = b'{"schema":"cutcontent.scene.v1","scene":{"groups":[]}}'
        self.assertIsNotNone(publication_check.private_artifact_problem("scene.json", package))
        for name in ("scene.scene", "scene.data", "guide.md"):
            self.assertIsNotNone(publication_check.private_artifact_problem(name, package))
        self.assertIsNone(publication_check.private_artifact_problem("guide.md", b'```json\n' + package + b'\n```'))
        self.assertIsNone(publication_check.private_artifact_problem("settings.json", b'{"theme":"dark"}'))


if __name__ == "__main__":
    unittest.main()
