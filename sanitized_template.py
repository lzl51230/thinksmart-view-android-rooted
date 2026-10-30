#!/usr/bin/env python3
"""Build or verify a full-size public template with zeroed device-specific regions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import uuid
import zlib

from firmware_tools import (
    CHUNK, IMAGE_NAMES, check_stock, digest_file, load_manifest, read_gpt, require,
)

FORMAT = "sanitized-full-emmc-template"
RELEASE = "v0.2.0"
NAMESPACE = "https://github.com/lzl51230/thinksmart-view-android-rooted/" + RELEASE


def canonical_gpt(stock, manifest):
    """Copy only generic partition types/attributes; generate every GUID anew."""
    size = manifest["image_bytes"]
    sectors = size // 512
    require(sectors > 100, "Image is too small for the canonical GPT")
    with Path(stock).open("rb") as stream:
        stream.seek(512)
        header = stream.read(512)
        table_lba, count, width = struct.unpack_from("<QII", header, 72)
        stream.seek(table_lba * 512)
        source_entries = stream.read(count * width)
    types = {}
    for position in range(0, len(source_entries), width):
        entry = source_entries[position:position + width]
        if entry[:16] == bytes(16):
            continue
        name = entry[56:128].decode("utf-16-le").split("\0", 1)[0]
        types[name] = (entry[:16], entry[48:56])
    require(len(manifest["layout"]) <= 128, "Too many partitions")
    table = bytearray(128 * 128)
    for index, partition in enumerate(manifest["layout"]):
        name = partition["name"]
        start = partition["start_sector"]
        end = start + partition["sectors"] - 1
        require(34 <= start <= end <= sectors - 34, "Partition overlaps canonical GPT")
        encoded = name.encode("utf-16-le")
        require(len(encoded) <= 72, "Partition name is too long")
        offset = index * 128
        table[offset:offset + 16] = types[name][0]
        table[offset + 16:offset + 32] = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE + "/" + name).bytes_le
        struct.pack_into("<QQ", table, offset + 32, start, end)
        table[offset + 48:offset + 56] = types[name][1]
        table[offset + 56:offset + 56 + len(encoded)] = encoded
    disk_guid = uuid.uuid5(uuid.NAMESPACE_URL, NAMESPACE + "/public-disk").bytes_le

    def make_header(current, alternate, table_start):
        raw = bytearray(512)
        raw[:8] = b"EFI PART"
        struct.pack_into("<IIIIQQQQ", raw, 8, 0x10000, 92, 0, 0,
                         current, alternate, 34, sectors - 34)
        raw[56:72] = disk_guid
        struct.pack_into("<QIII", raw, 72, table_start, 128, 128, zlib.crc32(table))
        struct.pack_into("<I", raw, 16, zlib.crc32(raw[:92]))
        return bytes(raw)

    mbr = bytearray(512)
    struct.pack_into("<B3sB3sII", mbr, 446, 0, b"\0\x02\0", 0xee,
                     b"\xff\xff\xff", 1, min(sectors - 1, 0xffffffff))
    mbr[510:512] = b"\x55\xaa"
    return [
        (0, bytes(mbr) + make_header(1, sectors - 1, 2) + bytes(table)),
        ((sectors - 33) * 512, bytes(table) + make_header(sectors - 1, 1, sectors - 33)),
    ]


def load_metadata(path):
    metadata = json.loads(Path(path).read_text())
    require(metadata.get("schema_version") == 1 and metadata.get("format") == FORMAT,
            "Unsupported template metadata")
    require(metadata.get("sector_size") == 512, "Unsupported sector size")
    require(metadata.get("directly_flashable") is False and
            metadata.get("requires_target_devices_own_stock_backup") is True,
            "A sanitized template must require personalization")
    regions = metadata["regions"]
    firmware = [entry for entry in regions if entry["kind"] == "firmware"]
    require(len(firmware) == 4 and {p["partition"] for p in firmware} == IMAGE_NAMES,
            "Only the four public firmware partitions may be retained")
    by_name = {p["name"]: p for p in metadata["layout"]}
    for entry in firmware:
        partition = by_name[entry["partition"]]
        require(entry["start"] == partition["start_sector"] * 512 and
                entry["bytes"] == partition["sectors"] * 512, "Firmware range is incompatible")
    gpt = [entry for entry in regions if entry["kind"] == "gpt"]
    require(len(regions) == 6 and len(gpt) == 2, "Unexpected nonzero region")
    expected_gpt = {(0, 34 * 512), (metadata["image_bytes"] - 33 * 512, 33 * 512)}
    require({(p["start"], p["bytes"]) for p in gpt} == expected_gpt, "Unexpected GPT ranges")
    cursor = 0
    for entry in sorted(regions, key=lambda p: p["start"]):
        require(entry["start"] >= cursor and entry["bytes"] > 0, "Template ranges overlap")
        cursor = entry["start"] + entry["bytes"]
    require(cursor <= metadata["image_bytes"], "Region exceeds image size")
    return metadata


def verify_template(template, metadata_path):
    metadata = load_metadata(metadata_path)
    read_gpt(template, metadata["image_bytes"], metadata["layout"])
    digest = hashlib.sha256()
    cursor = 0
    regions = sorted(metadata["regions"], key=lambda p: p["start"])
    with Path(template).open("rb") as stream:
        for region in regions + [{"start": metadata["image_bytes"], "bytes": 0}]:
            remaining = region["start"] - cursor
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                require(bool(block), "Truncated template")
                require(block.count(b"\0") == len(block),
                        "Device-specific or gap region is not zero")
                digest.update(block)
                remaining -= len(block)
            region_digest = hashlib.sha256()
            remaining = region["bytes"]
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                require(bool(block), "Truncated template")
                digest.update(block)
                region_digest.update(block)
                remaining -= len(block)
            if region["bytes"]:
                require(region_digest.hexdigest() == region["sha256"], "Template region checksum mismatch")
            cursor = region["start"] + region["bytes"]
    require(digest.hexdigest() == metadata["sha256"], "Full template checksum mismatch")
    return metadata


def template_manifest(metadata):
    return {
        "schema_version": 1, "release": metadata["release"],
        "sector_size": metadata["sector_size"], "image_bytes": metadata["image_bytes"],
        "stock_boot_sha256": metadata["stock_boot_sha256"], "layout": metadata["layout"],
        "images": [{"partition": p["partition"], "file": p["partition"] + ".img",
                    "bytes": p["bytes"], "sha256": p["sha256"]}
                   for p in metadata["regions"] if p["kind"] == "firmware"],
    }


def build_template(stock, firmware_directory, output, metadata_path):
    output, metadata_path = Path(output), Path(metadata_path)
    require(not output.exists() and not metadata_path.exists(), "Template output already exists")
    manifest = load_manifest(firmware_directory)
    check_stock(stock, manifest)
    regions = []
    created = False
    try:
        with output.open("xb") as destination:
            created = True
            destination.truncate(manifest["image_bytes"])
            for start, data in canonical_gpt(stock, manifest):
                destination.seek(start)
                destination.write(data)
                regions.append({"kind": "gpt", "start": start, "bytes": len(data),
                                "sha256": hashlib.sha256(data).hexdigest()})
            by_name = {p["name"]: p for p in manifest["layout"]}
            for image in manifest["images"]:
                partition = by_name[image["partition"]]
                start = partition["start_sector"] * 512
                destination.seek(start)
                with (Path(firmware_directory) / image["file"]).open("rb") as source:
                    remaining = image["bytes"]
                    while remaining:
                        block = source.read(min(CHUNK, remaining))
                        require(bool(block), "Firmware payload was truncated")
                        destination.write(block)
                        remaining -= len(block)
                regions.append({"kind": "firmware", "partition": image["partition"],
                                "start": start, "bytes": image["bytes"], "sha256": image["sha256"]})
            destination.flush()
            os.fsync(destination.fileno())
        metadata = {
            "schema_version": 1, "format": FORMAT, "release": RELEASE,
            "device_model": manifest.get("device_model", "ThinkSmart View CD-18781Y"),
            "base_firmware_release": manifest["release"],
            "sector_size": 512, "image_bytes": manifest["image_bytes"],
            "stock_boot_sha256": manifest["stock_boot_sha256"],
            "layout": manifest["layout"], "regions": sorted(regions, key=lambda p: p["start"]),
            "sha256": digest_file(output),
            "device_specific_and_unallocated_regions": "all zero",
            "gpt_guids": "public deterministic UUIDv5; no donor GUIDs retained",
            "directly_flashable": False,
            "requires_target_devices_own_stock_backup": True,
        }
        with metadata_path.open("x") as stream:
            json.dump(metadata, stream, indent=2)
            stream.write("\n")
        verify_template(output, metadata_path)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
        raise
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--stock-layout-source", type=Path, required=True)
    build.add_argument("--firmware-dir", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--metadata", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--template", type=Path, required=True)
    verify.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            metadata = build_template(args.stock_layout_source, args.firmware_dir,
                                      args.output, args.metadata)
        else:
            metadata = verify_template(args.template, args.metadata)
    except (ValueError, OSError) as error:
        parser.exit(1, "Template verification failed: " + str(error) + "\n")
    print(json.dumps({"bytes": metadata["image_bytes"], "sha256": metadata["sha256"],
                      "all_other_regions_zero": True, "directly_flashable": False}, indent=2))


if __name__ == "__main__":
    main()
