"""Verify GPT backups and build private recovery images without flashing a device."""
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

CHUNK = 4 * 1024 * 1024
IMAGE_NAMES = {"boot", "system", "vendor", "recovery"}


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest_region(stream, offset, size):
    stream.seek(offset)
    digest = hashlib.sha256()
    while size:
        block = stream.read(min(CHUNK, size))
        require(bool(block), "Unexpected end of image")
        digest.update(block)
        size -= len(block)
    return digest.hexdigest()


def load_manifest(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text())
    require(manifest.get("schema_version") == 1, "Unsupported manifest version")
    require(manifest.get("sector_size") == 512, "Only 512-byte sectors are supported")
    require(manifest["image_bytes"] % 512 == 0, "Invalid image size")
    layout = manifest["layout"]
    require(len({p["name"] for p in layout}) == len(layout), "Duplicate partition names")
    by_name = {p["name"]: p for p in layout}
    images = manifest["images"]
    require({p["partition"] for p in images} == IMAGE_NAMES and len(images) == 4,
            "The kit must contain exactly boot, system, vendor and recovery")
    for image in images:
        partition = by_name[image["partition"]]
        require(image["bytes"] == partition["sectors"] * 512, "Wrong partition image size")
        require(re.fullmatch(r"[0-9a-f]{64}", image["sha256"]), "Invalid SHA-256")
        path = (directory / image["file"]).resolve()
        require(path.is_relative_to(directory), "Image path escapes the firmware directory")
        require(path.is_file() and path.stat().st_size == image["bytes"],
                "Missing or truncated firmware image: " + image["partition"])
        require(digest_file(path) == image["sha256"],
                "Firmware checksum mismatch: " + image["partition"])
    return manifest


def read_gpt(path, expected_size, expected_layout):
    path = Path(path)
    require(path.stat().st_size == expected_size, "Backup size does not match this model")
    sectors = expected_size // 512
    with path.open("rb") as stream:
        def header(lba):
            require(0 < lba < sectors, "GPT header is outside the image")
            stream.seek(lba * 512)
            raw = stream.read(512)
            require(raw[:8] == b"EFI PART", "Missing GPT signature")
            length, checksum = struct.unpack_from("<II", raw, 12)
            require(92 <= length <= 512, "Invalid GPT header size")
            checked = bytearray(raw[:length])
            checked[16:20] = bytes(4)
            require(zlib.crc32(checked) == checksum, "GPT header checksum mismatch")
            current, alternate, first, last = struct.unpack_from("<QQQQ", raw, 24)
            require(current == lba and 1 < first <= last < sectors - 1, "Invalid GPT bounds")
            table_lba, count, width, table_crc = struct.unpack_from("<QIII", raw, 72)
            require(1 <= count <= 4096 and 128 <= width <= 4096, "Invalid GPT entry count")
            require(table_lba * 512 + count * width <= expected_size, "GPT table is outside the image")
            stream.seek(table_lba * 512)
            entries = stream.read(count * width)
            require(zlib.crc32(entries) == table_crc, "GPT partition table checksum mismatch")
            partitions = []
            for position in range(0, len(entries), width):
                entry = entries[position:position + width]
                if entry[:16] == bytes(16):
                    continue
                start, end = struct.unpack_from("<QQ", entry, 32)
                name = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
                require(first <= start <= end <= last, "Partition is outside usable space")
                partitions.append({"name": name, "start_sector": start, "sectors": end - start + 1})
            return alternate, first, last, raw[56:72], entries, partitions

        main = header(1)
        require(main[0] == sectors - 1, "Backup GPT is not at the last sector")
        backup = header(main[0])
        require(backup[0] == 1 and main[1:5] == backup[1:5], "The GPT copies disagree")
        actual = main[5]
        require(len({p["name"] for p in actual}) == len(actual), "Duplicate GPT partition names")
        require(sorted(actual, key=lambda p: p["name"]) ==
                sorted(expected_layout, key=lambda p: p["name"]), "Partition layout is incompatible")
        ordered = sorted(actual, key=lambda p: p["start_sector"])
        for left, right in zip(ordered, ordered[1:]):
            require(left["start_sector"] + left["sectors"] <= right["start_sector"],
                    "GPT partitions overlap")
    return {p["name"]: p for p in actual}


def check_stock(path, manifest):
    partitions = read_gpt(path, manifest["image_bytes"], manifest["layout"])
    boot = partitions["boot"]
    with Path(path).open("rb") as stream:
        actual = digest_region(stream, boot["start_sector"] * 512, boot["sectors"] * 512)
    require(actual == manifest["stock_boot_sha256"],
            "The backup boot fingerprint does not match the supported stock firmware")
    return partitions


def verify_output(stock, image, directory, manifest):
    partitions = check_stock(stock, manifest)
    read_gpt(image, manifest["image_bytes"], manifest["layout"])
    regions = sorted((partitions[p["partition"]]["start_sector"] * 512, p["bytes"], p["sha256"])
                     for p in manifest["images"])
    with Path(stock).open("rb") as source, Path(image).open("rb") as output:
        for start, size, expected in regions:
            require(digest_region(output, start, size) == expected, "A replaced partition differs")
        cursor = 0
        for start, size, _ in regions + [(manifest["image_bytes"], 0, "")]:
            source.seek(cursor)
            output.seek(cursor)
            remaining = start - cursor
            while remaining:
                length = min(CHUNK, remaining)
                require(source.read(length) == output.read(length),
                        "An area outside the four firmware partitions was changed")
                remaining -= length
            cursor = start + size
    return digest_file(image)
