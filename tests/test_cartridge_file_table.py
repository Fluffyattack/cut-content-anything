"""Cartridge file-table regressions: IDs, nested names, bounds and colours."""
import struct
import unittest
from unittest.mock import patch
import zlib

import fixture_builders as fixtures
from helpers import IsolatedTestCase
from cutcontent.core import service
from cutcontent.core.byte_sources import FileByteSource, MemoryByteSource
from cutcontent.core.scan_report import load_report
from cutcontent.formats import cartridge_file_table


class CartridgeFileTableTest(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.workspace / "example.cartridge"
        self.path.write_bytes(fixtures.cartridge_file_table_image())

    def scan(self):
        report = load_report(service.scan_path(self.path).build_id)
        return report, {item["name"]: item for item in report["items"]}

    def preview(self, report, item):
        return service.preview_item(report["build_id"], item["id"], enforce_allowed_folders=False)

    def test_header_files_banner_and_overlay_are_read(self):
        detection = service.detect_path(self.path)[0]
        self.assertEqual(detection.platform, "Cartridge with file table")
        self.assertEqual(detection.title, "Cartridge Example")
        report, items = self.scan()
        self.assertEqual(report["details"]["allocation_entries"], 4)
        self.assertEqual(report["details"]["named_files"], 3)
        self.assertEqual(report["details"]["overlay_files"], 1)
        self.assertIn("art/picture.png", items)
        self.assertTrue(items["Cartridge header"]["details"]["header checksum matches"])
        self.assertIn(b"TSTE", self.preview(report, items["Cartridge header"]).body)
        self.assertIn(b"Cartridge Example", self.preview(report, items["Cartridge titles"]).body)
        self.assertEqual(self.preview(report, items["art/picture.png"]).body[:8], b"\x89PNG\r\n\x1a\n")

    def test_file_ids_and_development_names_do_not_prove_unused_content(self):
        report, items = self.scan()
        overlay = items["Unnamed file ID 3"]
        self.assertTrue(overlay["details"]["listed in an overlay table"])
        self.assertFalse(overlay["is_finding"])
        self.assertEqual(overlay["evidence"]["possibly_unused"]["status"], "unknown")
        self.assertTrue(items["debug/unused_stage.txt"]["is_finding"])
        self.assertEqual(items["debug/unused_stage.txt"]["evidence"]["possibly_unused"]["status"], "unknown")
        for item in report["items"]:
            self.assertEqual(item["evidence"]["loaded_under_test"]["status"], "not_checked")

    def test_banner_tiling_palette_and_transparency(self):
        source = MemoryByteSource(fixtures.cartridge_file_table_image())
        banner = cartridge_file_table.read_banner(source, 0x8800)
        self.assertTrue(banner["checksum_ok"])
        png = cartridge_file_table.banner_icon_png(banner)
        self.assertEqual(struct.unpack_from(">II", png, 16), (32, 32))
        position, compressed = 8, b""
        while position < len(png):
            size = struct.unpack_from(">I", png, position)[0]
            if png[position + 4:position + 8] == b"IDAT":
                compressed += png[position + 8:position + 8 + size]
            position += size + 12
        row = zlib.decompress(compressed)
        self.assertEqual(row[1:5], bytes((255, 0, 0, 255)))
        self.assertEqual(row[8], 0)  # alpha of the second, transparent pixel
        self.assertEqual(row[1 + 8 * 4:1 + 9 * 4], bytes((0, 0, 255, 255)))

    def test_out_of_bounds_file_is_rejected(self):
        image = bytearray(fixtures.cartridge_file_table_image())
        struct.pack_into("<I", image, 0x8604, len(image) + 1)
        with self.assertRaisesRegex(cartridge_file_table.CartridgeFileTableError, "outside"):
            cartridge_file_table.read_file_system(MemoryByteSource(image), "fixture", "fixture")

    def test_directory_cycle_is_rejected(self):
        image = bytearray(fixtures.cartridge_file_table_image())
        link = image.find(b"\x83art", 0x8400)
        struct.pack_into("<H", image, link + 4, 0xF000)
        with self.assertRaisesRegex(cartridge_file_table.CartridgeFileTableError, "cycle"):
            cartridge_file_table.read_file_system(MemoryByteSource(image), "fixture", "fixture")

    def test_incomplete_file_is_reported_without_losing_the_rest_of_the_rom(self):
        image = bytearray(fixtures.cartridge_file_table_image())
        struct.pack_into("<I", image, 0x8604, len(image) + 1)
        self.path.write_bytes(image)
        report, items = self.scan()
        self.assertEqual(report["details"]["incomplete_file_ids"], [0])
        self.assertFalse(items["readme.txt"]["preview"]["supported"])
        self.assertEqual(items["readme.txt"]["evidence"]["present_in_data"]["status"], "unknown")
        self.assertTrue(report["warnings"])
        self.assertEqual(self.preview(report, items["art/picture.png"]).body[:4], b"\x89PNG")

    def test_secure_area_is_never_read_by_code_string_checks(self):
        image = bytearray(fixtures.cartridge_file_table_image())
        struct.pack_into("<IIII", image, 0x20, 0x4000, 0x02000000, 0x02000000, 0x4180)
        image[0x4000:0x4000 + 25] = b"secret debug area marker\0"
        struct.pack_into("<H", image, 0x15E, cartridge_file_table.crc16(image[:0x15E]))
        self.path.write_bytes(image)
        reads = []
        original = FileByteSource.read_at
        def observe(source, offset, length):
            reads.append((offset, length))
            return original(source, offset, length)
        with patch.object(FileByteSource, "read_at", observe):
            report, items = self.scan()
            text = self.preview(report, items["ARM9 executable: readable text strings"]).body
        self.assertNotIn(b"secret debug area marker", text)
        self.assertIn(b"Debug stage select menu", text)
        self.assertFalse(any(offset < 0x8000 and offset + length > 0x4000 for offset, length in reads))


if __name__ == "__main__":
    unittest.main()
