"""Repository hygiene: skill copies, generated docs, README promises, publication check."""

import subprocess
import sys
import unittest
from pathlib import Path

from helpers import IsolatedTestCase

from cutcontent.cli import format_support_markdown
from cutcontent.core.service import format_support_rows
from cutcontent.skill_sync import CLIENT_SKILL_FOLDERS, MAIN_SKILL_NAME, SKILLS_SOURCE, skill_copies_status, skill_names

ROOT = Path(__file__).resolve().parents[1]


class RepositoryTest(IsolatedTestCase):
    def test_skill_copies_are_identical_to_the_source(self):
        names = skill_names()
        self.assertIn(MAIN_SKILL_NAME, names)
        status = skill_copies_status()
        self.assertEqual(len(status), len(names) * len(CLIENT_SKILL_FOLDERS))
        for path, in_sync in status:
            self.assertTrue(in_sync, f"{path} is out of date - run: bin/cutcontent skill sync")

    def test_every_skill_has_front_matter_matching_its_folder(self):
        for name in skill_names():
            text = (SKILLS_SOURCE / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"---\nname: {name}\ndescription: "), name)

    def test_main_skill_keeps_the_evidence_model_and_routes_to_every_phase_skill(self):
        text = (SKILLS_SOURCE / MAIN_SKILL_NAME / "SKILL.md").read_text(encoding="utf-8")
        for phrase in ("present in the data", "possibly unused", "loaded under test conditions", "reachable in normal play", "DRM"):
            self.assertIn(phrase, text)
        for name in skill_names():
            if name != MAIN_SKILL_NAME:
                self.assertIn(f"`{name}`", text)

    def test_relative_links_in_documentation_resolve(self):
        import re
        documents = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CONTRIBUTING.md", ROOT / "DIRECTORY.md"]
        documents += sorted((ROOT / "playbook").glob("*.md")) + sorted((ROOT / "games").rglob("*.md")) + sorted((ROOT / "data").glob("*.md"))
        for document in documents:
            for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", document.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                self.assertTrue((document.parent / target).exists(), f"{document.relative_to(ROOT)} links to missing {target}")

    def test_directory_page_is_generated_from_valid_data(self):
        from cutcontent import directory
        self.assertEqual(directory.validate_entries(directory.load_entries()), [])
        self.assertTrue(directory.build_page(check_only=True), "DIRECTORY.md is out of date - run: bin/cutcontent directory build")

    def test_format_document_matches_the_adapters(self):
        document = (ROOT / "docs" / "FORMAT_SUPPORT.md").read_text(encoding="utf-8")
        self.assertIn(format_support_markdown(format_support_rows()), document)

    def test_every_data_family_is_documented(self):
        families = " ".join(row["platform"] for row in format_support_rows())
        for name in ("Cartridge with file table", "8-bit cartridges", "32-bit cartridges",
                     "Disc with file table", "Disc with encrypted partitions",
                     "CD image (ISO 9660)", "DVD image (ISO 9660)",
                     "Disc image with parameter file", "DVD image with tree directories", "PC"):
            self.assertIn(name, families)

    def test_readme_starts_with_the_ai_disclosure_and_licence_status(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        position = readme.find("\n## AI-assisted development")
        self.assertGreater(position, 0)
        self.assertLess(readme[:position].count("\n## "), 2, "the AI section must be near the top")
        self.assertIn("not open source", readme.lower())

    def test_publication_check_passes(self):
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_publication.py")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
