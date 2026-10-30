import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

from firmware_tools import VerificationError, load_manifest, read_gpt, verify_output
from prepare_restore import prepare


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kit = self.root / "kit"
        self.kit.mkdir()
        self.stock = self.root / "stock.img"
        self.output = self.root / "rooted.img"
        names = ["boot", "recovery", "system", "vendor", "persist", "userdata"]
        self.layout = [{"name": name, "start_sector": 16 + index * 8, "sectors": 8}
                       for index, name in enumerate(names)]
        data = bytearray((index * 37 + 19) % 256 for index in range(128 * 512))
        table = bytearray(8 * 128)
        for index, part in enumerate(self.layout):
            offset = index * 128
            table[offset:offset + 16] = uuid.UUID(int=1).bytes_le
            table[offset + 16:offset + 32] = uuid.UUID(int=index + 10).bytes_le
            struct.pack_into("<QQ", table, offset + 32, part["start_sector"],
                             part["start_sector"] + part["sectors"] - 1)
            encoded = part["name"].encode("utf-16-le")
            table[offset + 56:offset + 56 + len(encoded)] = encoded
        disk_guid = uuid.UUID(int=42).bytes_le

        def header(lba, alternate, table_lba):
            raw = bytearray(512)
            raw[:8] = b"EFI PART"
            struct.pack_into("<IIIIQQQQ", raw, 8, 0x10000, 92, 0, 0,
                             lba, alternate, 8, 120)
            raw[56:72] = disk_guid
            struct.pack_into("<QIII", raw, 72, table_lba, 8, 128, zlib.crc32(table))
            struct.pack_into("<I", raw, 16, zlib.crc32(raw[:92]))
            return raw

        data[512:1024] = header(1, 127, 2)
        data[1024:2048] = table
        data[125 * 512:127 * 512] = table
        data[127 * 512:] = header(127, 1, 125)
        self.stock.write_bytes(data)
        images = []
        for index, part in enumerate(self.layout[:4]):
            payload = bytes([index + 1]) * (part["sectors"] * 512)
            name = part["name"] + ".img"
            (self.kit / name).write_bytes(payload)
            images.append({"partition": part["name"], "file": name, "bytes": len(payload),
                           "sha256": hashlib.sha256(payload).hexdigest()})
        boot = self.layout[0]
        boot_bytes = data[boot["start_sector"] * 512:
                          (boot["start_sector"] + boot["sectors"]) * 512]
        self.manifest = {
            "schema_version": 1, "release": "test", "sector_size": 512,
            "image_bytes": len(data), "layout": self.layout, "images": images,
            "stock_boot_sha256": hashlib.sha256(boot_bytes).hexdigest(),
        }
        self.save_manifest()

    def save_manifest(self):
        (self.kit / "manifest.json").write_text(json.dumps(self.manifest))

    def test_success_preserves_private_partitions_and_gpts(self):
        before = self.stock.read_bytes()
        report = prepare(self.stock, self.kit, self.output)
        self.assertTrue(report["all_other_regions_identical_to_stock_backup"])
        self.assertTrue(report["do_not_upload"])
        self.assertEqual(before, self.stock.read_bytes())
        result = self.output.read_bytes()
        for part in self.layout[4:]:
            start, end = part["start_sector"] * 512, (part["start_sector"] + part["sectors"]) * 512
            self.assertEqual(before[start:end], result[start:end])
        self.assertEqual(report["sha256"], hashlib.sha256(result).hexdigest())
        self.assertTrue(Path(str(self.output) + ".sha256").exists())

    def test_refuses_existing_output(self):
        self.output.write_bytes(b"keep")
        with self.assertRaises(VerificationError):
            prepare(self.stock, self.kit, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_known_stock_backup_checksum(self):
        digest = hashlib.sha256(self.stock.read_bytes()).hexdigest()
        Path(str(self.stock) + ".sha256").write_text(digest + "  stock.img\n")
        report = prepare(self.stock, self.kit, self.output)
        self.assertTrue(report["stock_backup_sha256_verified"])

    def test_wrong_stock_backup_checksum(self):
        with self.assertRaisesRegex(VerificationError, "Stock backup SHA-256 mismatch"):
            prepare(self.stock, self.kit, self.output, "0" * 64)
        self.assertFalse(self.output.exists())

    def test_refuses_input_as_output(self):
        with self.assertRaises(VerificationError):
            prepare(self.stock, self.kit, self.stock)

    def test_truncated_backup(self):
        self.stock.write_bytes(self.stock.read_bytes()[:-512])
        with self.assertRaisesRegex(VerificationError, "size"):
            prepare(self.stock, self.kit, self.output)

    def test_primary_gpt_corruption(self):
        with self.stock.open("r+b") as stream:
            stream.seek(512 + 40)
            stream.write(b"\xff")
        with self.assertRaisesRegex(VerificationError, "GPT header checksum"):
            prepare(self.stock, self.kit, self.output)

    def test_backup_gpt_corruption(self):
        with self.stock.open("r+b") as stream:
            stream.seek(127 * 512)
            stream.write(b"NOT GPT!")
        with self.assertRaisesRegex(VerificationError, "GPT signature"):
            prepare(self.stock, self.kit, self.output)

    def test_partition_table_corruption(self):
        with self.stock.open("r+b") as stream:
            stream.seek(1024)
            stream.write(b"\xff")
        with self.assertRaisesRegex(VerificationError, "partition table checksum"):
            prepare(self.stock, self.kit, self.output)

    def test_layout_mismatch(self):
        self.manifest["layout"][-1]["start_sector"] += 1
        self.save_manifest()
        with self.assertRaisesRegex(VerificationError, "layout"):
            prepare(self.stock, self.kit, self.output)

    def test_wrong_stock_firmware(self):
        self.manifest["stock_boot_sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(VerificationError, "boot fingerprint"):
            prepare(self.stock, self.kit, self.output)

    def test_truncated_payload(self):
        (self.kit / "system.img").write_bytes(b"short")
        with self.assertRaisesRegex(VerificationError, "truncated"):
            prepare(self.stock, self.kit, self.output)

    def test_bad_payload_checksum(self):
        (self.kit / "system.img").write_bytes(bytes(4096))
        with self.assertRaisesRegex(VerificationError, "checksum"):
            prepare(self.stock, self.kit, self.output)

    def test_manifest_path_escape(self):
        self.manifest["images"][0]["file"] = "../stock.img"
        self.save_manifest()
        with self.assertRaisesRegex(VerificationError, "escapes"):
            prepare(self.stock, self.kit, self.output)

    def test_detects_private_partition_modification(self):
        prepare(self.stock, self.kit, self.output)
        with self.output.open("r+b") as stream:
            stream.seek(self.layout[-1]["start_sector"] * 512)
            stream.write(b"\0")
        with self.assertRaisesRegex(VerificationError, "outside"):
            verify_output(self.stock, self.output, self.kit, self.manifest)

    def test_detects_firmware_partition_modification(self):
        prepare(self.stock, self.kit, self.output)
        with self.output.open("r+b") as stream:
            stream.seek(self.layout[0]["start_sector"] * 512)
            stream.write(b"\0")
        with self.assertRaisesRegex(VerificationError, "replaced partition"):
            verify_output(self.stock, self.output, self.kit, self.manifest)


if __name__ == "__main__":
    unittest.main()
