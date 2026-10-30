import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
import zlib

from firmware_tools import VerificationError, verify_output
from personalize_image import personalize
from sanitized_template import build_template, verify_template, template_manifest


class SanitizedTemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.kit = self.root / "kit"
        self.kit.mkdir()
        self.stock = self.root / "stock.img"
        self.template = self.root / "public.img"
        self.metadata = self.root / "template.json"
        self.output = self.root / "private.img"
        names = ["boot", "recovery", "system", "vendor", "persist", "userdata"]
        self.layout = [{"name": name, "start_sector": 64 + index * 8, "sectors": 8}
                       for index, name in enumerate(names)]
        data = bytearray((index * 31 + 17) % 256 for index in range(512 * 512))
        table = bytearray(8 * 128)
        for index, part in enumerate(self.layout):
            offset = index * 128
            table[offset:offset + 16] = uuid.UUID(int=1).bytes_le
            table[offset + 16:offset + 32] = uuid.UUID(int=index + 10).bytes_le
            struct.pack_into("<QQ", table, offset + 32, part["start_sector"],
                             part["start_sector"] + part["sectors"] - 1)
            name = part["name"].encode("utf-16-le")
            table[offset + 56:offset + 56 + len(name)] = name

        def header(lba, other, entries_lba):
            raw = bytearray(512)
            raw[:8] = b"EFI PART"
            struct.pack_into("<IIIIQQQQ", raw, 8, 0x10000, 92, 0, 0, lba, other, 34, 478)
            raw[56:72] = uuid.UUID(int=42).bytes_le
            struct.pack_into("<QIII", raw, 72, entries_lba, 8, 128, zlib.crc32(table))
            struct.pack_into("<I", raw, 16, zlib.crc32(raw[:92]))
            return raw

        data[512:1024] = header(1, 511, 2)
        data[1024:2048] = table
        data[509 * 512:511 * 512] = table
        data[511 * 512:] = header(511, 1, 509)
        self.stock.write_bytes(data)
        images = []
        for index, part in enumerate(self.layout[:4]):
            payload = bytes([index + 1]) * (part["sectors"] * 512)
            filename = part["name"] + ".img"
            (self.kit / filename).write_bytes(payload)
            images.append({"partition": part["name"], "file": filename,
                           "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        boot = self.layout[0]
        start, size = boot["start_sector"] * 512, boot["sectors"] * 512
        manifest = {
            "schema_version": 1, "release": "fixture", "device_model": "fixture",
            "sector_size": 512, "image_bytes": len(data), "layout": self.layout,
            "stock_boot_sha256": hashlib.sha256(data[start:start + size]).hexdigest(),
            "images": images,
        }
        (self.kit / "manifest.json").write_text(json.dumps(manifest))
        self.original = bytes(data)

    def build(self):
        return build_template(self.stock, self.kit, self.template, self.metadata)

    def test_zeroes_private_partitions_gaps_and_regenerates_guids(self):
        metadata = self.build()
        data = self.template.read_bytes()
        self.assertEqual(self.stock.read_bytes(), self.original)
        self.assertFalse(metadata["directly_flashable"])
        self.assertNotEqual(data[568:584], self.original[568:584])
        self.assertNotEqual(data[1040:1056], self.original[1040:1056])
        for part in self.layout[4:]:
            start, size = part["start_sector"] * 512, part["sectors"] * 512
            self.assertEqual(data[start:start + size], bytes(size))
        self.assertEqual(data[40 * 512:64 * 512], bytes(24 * 512))
        self.assertEqual(metadata["sha256"], hashlib.sha256(data).hexdigest())
        verify_template(self.template, self.metadata)

    def test_private_partition_contamination_is_rejected(self):
        self.build()
        with self.template.open("r+b") as stream:
            stream.seek(self.layout[-1]["start_sector"] * 512)
            stream.write(b"fake-private-account")
        with self.assertRaisesRegex(VerificationError, "not zero"):
            verify_template(self.template, self.metadata)

    def test_unallocated_gap_contamination_is_rejected(self):
        self.build()
        with self.template.open("r+b") as stream:
            stream.seek(40 * 512)
            stream.write(b"fake-private-key")
        with self.assertRaisesRegex(VerificationError, "not zero"):
            verify_template(self.template, self.metadata)

    def test_changed_firmware_is_rejected(self):
        self.build()
        with self.template.open("r+b") as stream:
            stream.seek(self.layout[2]["start_sector"] * 512)
            stream.write(b"\0")
        with self.assertRaisesRegex(VerificationError, "region checksum"):
            verify_template(self.template, self.metadata)

    def test_truncated_template_is_rejected(self):
        self.build()
        self.template.write_bytes(self.template.read_bytes()[:-512])
        with self.assertRaisesRegex(VerificationError, "size"):
            verify_template(self.template, self.metadata)

    def test_existing_template_is_preserved(self):
        self.template.write_bytes(b"keep")
        with self.assertRaises(VerificationError):
            self.build()
        self.assertEqual(self.template.read_bytes(), b"keep")

    def test_metadata_cannot_allow_a_private_partition(self):
        self.build()
        metadata = json.loads(self.metadata.read_text())
        private = self.layout[-1]
        metadata["regions"].append({
            "kind": "firmware", "partition": "userdata",
            "start": private["start_sector"] * 512, "bytes": private["sectors"] * 512,
            "sha256": "0" * 64,
        })
        self.metadata.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(VerificationError, "four public"):
            verify_template(self.template, self.metadata)

    def test_metadata_cannot_claim_template_is_flashable(self):
        self.build()
        metadata = json.loads(self.metadata.read_text())
        metadata["directly_flashable"] = True
        self.metadata.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(VerificationError, "personalization"):
            verify_template(self.template, self.metadata)

    def test_personalization_uses_recipients_own_data_and_guids(self):
        self.build()
        recipient = self.root / "recipient.img"
        data = bytearray(self.original)
        private_start = self.layout[-1]["start_sector"] * 512
        data[private_start:private_start + 19] = b"recipient-only-data"
        for lba in [1, 511]:
            start = lba * 512
            data[start + 56:start + 72] = uuid.UUID(int=99).bytes_le
            data[start + 16:start + 20] = bytes(4)
            struct.pack_into("<I", data, start + 16, zlib.crc32(data[start:start + 92]))
        recipient.write_bytes(data)
        report = personalize(self.template, self.metadata, recipient, self.output)
        result = self.output.read_bytes()
        self.assertEqual(result[private_start:private_start + 19], b"recipient-only-data")
        self.assertEqual(result[568:584], uuid.UUID(int=99).bytes_le)
        self.assertEqual(recipient.read_bytes(), data)
        self.assertTrue(report["target_device_gpt_and_other_regions_restored_from_own_backup"])
        self.assertTrue(report["do_not_upload"])

    def test_personalization_refuses_existing_output(self):
        self.build()
        self.output.write_bytes(b"keep")
        with self.assertRaises(VerificationError):
            personalize(self.template, self.metadata, self.stock, self.output)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_metadata_verifies_personalized_readback_without_partition_files(self):
        metadata = self.build()
        report = personalize(self.template, self.metadata, self.stock, self.output)
        digest = verify_output(self.stock, self.output, None, template_manifest(metadata))
        self.assertEqual(digest, report["sha256"])

    def test_personalization_rejects_wrong_backup_boot(self):
        self.build()
        with self.stock.open("r+b") as stream:
            stream.seek(self.layout[0]["start_sector"] * 512)
            stream.write(b"\0")
        with self.assertRaisesRegex(VerificationError, "boot fingerprint"):
            personalize(self.template, self.metadata, self.stock, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
