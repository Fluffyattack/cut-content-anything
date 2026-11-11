"""The library must not parse every full asset report on each page load."""
import json
from pathlib import Path
from unittest.mock import patch

from helpers import IsolatedTestCase
from cutcontent.core import service
from cutcontent.core.scan_report import list_reports, load_report, report_summaries_directory, reports_directory
from cutcontent.core.settings import write_json_atomically
from cutcontent.demo import create_demo_game


class ReportSummariesTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.report = service.scan_path(create_demo_game())
        self.report_path = reports_directory() / f"{self.report.build_id}.json"

    def test_library_uses_summary_without_reading_full_asset_rows(self):
        original = Path.read_text
        def read_without_report(path, *arguments, **options):
            if path == self.report_path:
                self.fail("The library reread the full asset report instead of its summary.")
            return original(path, *arguments, **options)
        with patch.object(Path, "read_text", read_without_report):
            summaries = list_reports()
        self.assertEqual(summaries[0]["build_id"], self.report.build_id)
        self.assertEqual(summaries[0]["statistics"], self.report.statistics())

    def test_old_reports_get_a_summary_and_modifications_invalidate_it(self):
        summary_path = report_summaries_directory() / self.report_path.name
        summary_path.unlink()
        self.assertEqual(list_reports()[0]["title"], self.report.title)
        self.assertTrue(summary_path.is_file())
        payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        payload["title"] = "A changed report title"
        write_json_atomically(self.report_path, payload)
        self.assertEqual(list_reports()[0]["title"], "A changed report title")

    def test_removed_adapter_is_resolved_from_source_without_losing_item_ids(self):
        payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        original_item_ids = [item["id"] for item in payload["items"]]
        payload.update(adapter="removed_adapter", platform="Old label", format_name="Old format")
        write_json_atomically(self.report_path, payload)

        restored = load_report(self.report.build_id)
        self.assertEqual(restored["adapter"], "quake")
        self.assertEqual([item["id"] for item in restored["items"]], original_item_ids)
        text_item = next(item for item in restored["items"] if item["name"] == "cutcontent-demo.txt")
        preview = service.preview_item(self.report.build_id, text_item["id"], enforce_allowed_folders=False)
        self.assertIn(b"Cut Content Anything", preview.body)
        self.assertEqual(list_reports()[0]["platform"], restored["platform"])

    def test_cached_summary_with_removed_adapter_is_refreshed(self):
        summary_path = report_summaries_directory() / self.report_path.name
        cached = json.loads(summary_path.read_text(encoding="utf-8"))
        cached["summary"].update(adapter="removed_adapter", platform="Old label", format_name="Old format")
        write_json_atomically(summary_path, cached)

        summaries = list_reports()
        self.assertEqual(summaries[0]["adapter"], "quake")
        self.assertEqual(summaries[0]["platform"], self.report.platform)
        self.assertEqual(json.loads(summary_path.read_text(encoding="utf-8"))["summary"]["adapter"], "quake")
