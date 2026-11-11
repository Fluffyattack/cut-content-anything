"""Every data-family adapter against self-made images: detection, scan, evidence and previews."""

import unittest

import fixture_builders as fixtures
from helpers import IsolatedTestCase

from cutcontent.core import service
from cutcontent.core.byte_sources import MemoryByteSource
from cutcontent.core.scan_report import load_report
from cutcontent.formats import iso9660, disc_metadata


class PlatformAdapterTest(IsolatedTestCase):
    def scan(self, path):
        detections = service.detect_path(path)
        report = load_report(service.scan_path(path).build_id)
        return detections, report, self.items_by_name(report)

    # ------------------------------------------------------------- Cartridge images
    def test_eight_bit_cartridge_rom(self):
        path = self.workspace / "eight_bit.cartridge"
        path.write_bytes(fixtures.eight_bit_cartridge_rom())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "8-bit cartridge (colour)")
        self.assertEqual(report["title"], "CCA 8BITROM")
        self.assertIn("DEBUG MENU - STAGE SELECT", items)
        self.assertEqual(items["DEBUG MENU - STAGE SELECT"]["evidence"]["possibly_unused"]["status"], "unknown")
        tiles = items["Tile browser (whole ROM)"]
        png = service.preview_item(report["build_id"], tiles["id"], {"offset": 0x3000, "bits": 2}, enforce_allowed_folders=False)
        self.assertEqual(png.body[:4], b"\x89PNG")

    def test_thirty_two_bit_cartridge_rom_in_zip(self):
        import zipfile

        path = self.workspace / "test.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("thirty_two_bit.cartridge", fixtures.thirty_two_bit_cartridge_rom())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "32-bit cartridge")
        self.assertEqual(report["title"], "CCA32BITROM")
        self.assertIn("SOUND TEST MODE", items)
        self.assertEqual(items["SOUND TEST MODE"]["location"]["internal_path"], "thirty_two_bit.cartridge")

    def test_rom_with_bad_checksum_is_not_detected(self):
        rom = bytearray(fixtures.eight_bit_cartridge_rom())
        rom[0x14D] ^= 0xFF
        path = self.workspace / "broken.cartridge"
        path.write_bytes(bytes(rom))
        self.assertEqual(service.detect_path(path), [])

    # ---------------------------------------------------------------------- ISO 9660 discs
    def test_raw_cd_image_with_cue(self):
        cue = fixtures.raw_cd_image_with_cue(self.workspace)
        detections, report, items = self.scan(cue)
        self.assertEqual(detections[0].platform, "CD image (ISO 9660)")
        self.assertEqual(items["DATA/UNUSED_BOSS.DAT"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["DATA/LEVEL1.DAT"]["evidence"]["possibly_unused"]["status"], "no")
        self.assertIn("GAME_000.01", report["details"]["reference_sources"])

    def test_dvd_iso_image(self):
        path = self.workspace / "dvd.iso"
        path.write_bytes(fixtures.dvd_iso_image())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "DVD image (ISO 9660)")
        self.assertEqual(items["MODELS/PROTO_CAR.MDL"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["MODELS/HERO.MDL"]["evidence"]["possibly_unused"]["status"], "no")

    def test_parameter_disc_cso_keeps_encrypted_executable_closed(self):
        path = self.workspace / "parameter.cso"
        path.write_bytes(disc_metadata.build_compressed_iso(fixtures.parameter_file_disc_image()))
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "Disc image with parameter file (ISO 9660)")
        self.assertEqual(report["title"], "CCA Parameter Disc Test")
        self.assertEqual(items["DISC_GAME/USRDIR/DATA.BIN"]["evidence"]["possibly_unused"]["status"], "unknown")
        self.assertTrue(any("does not decrypt" in limit for limit in report["limits"]))
        icon = service.preview_item(report["build_id"], items["DISC_GAME/ICON0.PNG"]["id"], enforce_allowed_folders=False)
        self.assertEqual(icon.body[:4], b"\x89PNG")
        sfo = service.preview_item(report["build_id"], items["DISC_GAME/PARAM.SFO"]["id"], enforce_allowed_folders=False)
        self.assertIn(b"DISC_ID = TEST00000", sfo.body)

    def test_cso_reader_matches_the_plain_image(self):
        iso = fixtures.parameter_file_disc_image()
        compressed = disc_metadata.CompressedIsoSource(MemoryByteSource(disc_metadata.build_compressed_iso(iso)))
        self.assertEqual(compressed.read_at(0, len(iso)), iso)
        self.assertEqual(compressed.read_at(16 * 2048 + 1, 5), b"CD001")

    def test_compressed_iso_with_empty_header_size_is_scanned(self):
        image = bytearray(disc_metadata.build_compressed_iso(fixtures.parameter_file_disc_image()))
        image[4:8] = bytes(4)  # observed in local images; the block index still begins at byte 24
        path = self.workspace / "empty_header_size.cso"
        path.write_bytes(image)
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "Disc image with parameter file (ISO 9660)")
        icon = service.preview_item(report["build_id"], items["DISC_GAME/ICON0.PNG"]["id"], enforce_allowed_folders=False)
        self.assertEqual(icon.body[:8], b"\x89PNG\r\n\x1a\n")

    def test_parameter_disc_empty_update_parameters_do_not_break_the_preview(self):
        # Real disc images can keep an empty update PARAM.SFO beside the valid game table.
        _, originals = iso9660.list_files(MemoryByteSource(fixtures.parameter_file_disc_image()), "test", "test")
        files = {file.path: file.read() for file in originals}
        files["DISC_GAME/SYSDIR/UPDATE/PARAM.SFO"] = b""
        path = self.workspace / "placeholder.cso"
        path.write_bytes(disc_metadata.build_compressed_iso(iso9660.build_iso(files)))
        _, report, items = self.scan(path)
        self.assertEqual(report["title"], "CCA Parameter Disc Test")
        self.assertFalse(items["DISC_GAME/SYSDIR/UPDATE/PARAM.SFO"]["preview"]["supported"])
        self.assertIn("empty placeholder", items["DISC_GAME/SYSDIR/UPDATE/PARAM.SFO"]["preview"]["reason"])
        preview = service.preview_item(report["build_id"], items["DISC_GAME/PARAM.SFO"]["id"], enforce_allowed_folders=False)
        self.assertIn(b"DISC_ID = TEST00000", preview.body)

    def test_signed_executable_folder_is_detection_only(self):
        folder = fixtures.signed_executable_folder(self.workspace)
        detections, report, items = self.scan(folder)
        self.assertEqual(detections[0].platform, "Game folder with signed executables")
        self.assertEqual(report["title"], "CCA Signed Folder Test")
        self.assertEqual(items["SIGNED_GAME/USRDIR/level_test.dat"]["evidence"]["possibly_unused"]["status"], "unknown")
        self.assertTrue(any("signed and encrypted executable" in limit for limit in report["limits"]))

    def test_chd_is_refused_with_a_reason(self):
        folder = self.workspace / "psx"
        folder.mkdir()
        path = folder / "game.chd"
        path.write_bytes(b"MComprHD" + bytes(200))
        detections, report, items = self.scan(path)
        self.assertIn("not supported", detections[0].format_name)
        self.assertIn("chdman", report["items"][0]["preview"]["reason"])

    def test_iso_round_trip(self):
        image = iso9660.build_iso({"A.TXT": b"a", "DIR/SUB/B.BIN": b"b" * 3000})
        _, files = iso9660.list_files(MemoryByteSource(image), "test", "test")
        sizes = {file.path: file.size for file in files}
        self.assertEqual(sizes, {"A.TXT": 1, "DIR/SUB/B.BIN": 3000})

    def test_gzip_disc_in_nested_console_library_is_shown_with_a_reason(self):
        folder = self.workspace / "DiscLibrary" / "Adventures"
        folder.mkdir(parents=True)
        path = folder / "game.gz"
        path.write_bytes(b"\x1f\x8b" + bytes(30))
        detections, report, _ = self.scan(path)
        self.assertEqual(detections[0].format_name, "Packed or compressed image (not supported)")
        self.assertIn("Decompress a separate copy", report["limits"][0])

    # ---------------------------------------------------------- File-table discs
    def test_file_table_disc_image(self):
        path = self.workspace / "table.iso"
        path.write_bytes(fixtures.file_table_disc_image())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "Disc with file table")
        self.assertEqual(report["title"], "CCA File Table Disc Test")
        self.assertEqual(items["data/old_stage.arc"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["data/stage1.arc"]["evidence"]["possibly_unused"]["status"], "no")
        banner = service.preview_item(report["build_id"], items["opening.bnr"]["id"], enforce_allowed_folders=False)
        self.assertEqual(banner.body[:4], b"\x89PNG")

    def test_extracted_file_table_folder(self):
        folder = fixtures.extracted_file_table_folder(self.workspace)
        detections, report, items = self.scan(folder)
        self.assertEqual(detections[0].format_name, "Extracted disc folder")
        self.assertEqual(items["data/old_stage.arc"]["evidence"]["possibly_unused"]["status"], "yes")

    def test_encrypted_partition_is_not_decrypted(self):
        path = self.workspace / "partition.iso"
        path.write_bytes(fixtures.encrypted_partition_header_image())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "Disc with encrypted partitions")
        self.assertEqual(report["title"], "CCA Encrypted Test Disc")
        self.assertIn("does not decrypt", report["limits"][0])

    def test_rvz_is_refused(self):
        path = self.workspace / "game.rvz"
        path.write_bytes(b"RVZ\x01" + bytes(508))
        _, report, _ = self.scan(path)
        self.assertIn("Convert a copy", report["limits"][0])

    # --------------------------------------------------------------------- Tree-directory discs
    def test_tree_directory_image(self):
        path = self.workspace / "tree.iso"
        path.write_bytes(fixtures.tree_directory_image())
        detections, report, items = self.scan(path)
        self.assertEqual(detections[0].platform, "DVD image with tree directories")
        self.assertEqual(report["title"], "CCA Tree Directory Test")
        self.assertEqual(items["media/cut_level.pack"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["media/level1.pack"]["evidence"]["possibly_unused"]["status"], "no")
        sound = service.preview_item(report["build_id"], items["sound/menu.wav"]["id"], enforce_allowed_folders=False)
        self.assertEqual(sound.body[:4], b"RIFF")

    def test_encrypted_executable_folder_is_detection_only(self):
        folder = fixtures.encrypted_executable_folder(self.workspace)
        detections, report, items = self.scan(folder)
        self.assertEqual(detections[0].platform, "DVD image with tree directories and encrypted executables")
        self.assertEqual(items["media/pack.bin"]["evidence"]["possibly_unused"]["status"], "unknown")

    # ----------------------------------------------------------------------- PC
    def test_generic_pc_folder(self):
        folder = fixtures.pc_game_folder(self.workspace)
        detections, report, items = self.scan(folder)
        self.assertEqual(detections[0].adapter, "generic_folder")
        self.assertEqual(items["data/old_logo.png"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["sounds/beta_theme.wav"]["evidence"]["possibly_unused"]["status"], "yes")
        self.assertEqual(items["data/intro.png"]["evidence"]["possibly_unused"]["status"], "no")
        image = service.preview_item(report["build_id"], items["data/intro.png"]["id"], enforce_allowed_folders=False)
        self.assertEqual(image.body[:4], b"\x89PNG")

    def test_reference_check_switches_itself_off_when_names_are_missing(self):
        folder = self.workspace / "Indexed Game"
        folder.mkdir()
        (folder / "game.exe").write_bytes(b"MZ" + bytes(100) + b"nothing useful here\x00")
        for index in range(6):
            (folder / f"blob{index}.bin").write_bytes(bytes([index]) * 10)
        _, report, items = self.scan(folder)
        self.assertEqual(items["blob0.bin"]["evidence"]["possibly_unused"]["status"], "unknown")
        self.assertTrue(any("not meaningful" in limit or "says little" in limit for limit in report["limits"]))


if __name__ == "__main__":
    unittest.main()
