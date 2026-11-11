"""Shared test set-up: every test gets its own empty data directory."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


class IsolatedTestCase(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.data_directory = self.workspace / "data"
        self._saved_environment = {key: os.environ.get(key) for key in ("CUT_CONTENT_DATA_DIR", "CUT_CONTENT_ROM_DIR", "CUT_CONTENT_QWASM_DIR")}
        os.environ["CUT_CONTENT_DATA_DIR"] = str(self.data_directory)
        os.environ.pop("CUT_CONTENT_ROM_DIR", None)
        os.environ.pop("CUT_CONTENT_QWASM_DIR", None)

    def tearDown(self):
        for key, value in self._saved_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._temporary.cleanup()

    @staticmethod
    def items_by_name(report: dict) -> dict:
        return {item["name"]: item for item in report["items"]}
