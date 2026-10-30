#!/usr/bin/env python3
"""Build a private full recovery image using this device's own stock backup."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil

from firmware_tools import CHUNK, check_stock, digest_file, load_manifest, require, verify_output


def prepare(stock, directory, output, stock_sha256=None):
    stock, directory, output = Path(stock), Path(directory), Path(output)
    require(stock.resolve() != output.resolve(), "Input and output must be different")
    require(not output.exists(), "Refusing to overwrite an existing output")
    require(not Path(str(output) + ".sha256").exists() and
            not Path(str(output) + ".json").exists(), "Output report already exists")
    manifest = load_manifest(directory)
    partitions = check_stock(stock, manifest)
    checksum_source = Path(str(stock) + ".sha256")
    if stock_sha256 is None and checksum_source.exists():
        contents = checksum_source.read_text().split()
        require(bool(contents), "The stock backup checksum file is empty")
        stock_sha256 = contents[0].lower()
    if stock_sha256 is not None:
        require(re.fullmatch(r"[0-9a-f]{64}", stock_sha256) is not None,
                "Invalid stock backup SHA-256")
        require(digest_file(stock) == stock_sha256, "Stock backup SHA-256 mismatch")
    require(output.parent.is_dir(), "Create the output directory first")
    require(shutil.disk_usage(output.parent).free >= manifest["image_bytes"],
            "Not enough free space for the full recovery image")
    created = False
    try:
        with output.open("xb") as destination:
            created = True
            os.chmod(output, 0o600)
            with stock.open("rb") as source:
                shutil.copyfileobj(source, destination, CHUNK)
            for image in manifest["images"]:
                destination.seek(partitions[image["partition"]]["start_sector"] * 512)
                with (directory / image["file"]).open("rb") as source:
                    shutil.copyfileobj(source, destination, CHUNK)
            destination.flush()
            os.fsync(destination.fileno())
        digest = verify_output(stock, output, directory, manifest)
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise
    report = {
        "image": str(output.resolve()), "bytes": manifest["image_bytes"],
        "sha256": digest, "release": manifest["release"],
        "replaced_partitions": [image["partition"] for image in manifest["images"]],
        "all_other_regions_identical_to_stock_backup": True,
        "primary_and_backup_gpt_valid": True,
        "contains_private_device_data": True,
        "do_not_upload": True,
        "stock_backup_sha256_verified": stock_sha256 is not None,
    }
    checksum = Path(str(output) + ".sha256")
    report_path = Path(str(output) + ".json")
    for path, content in [(checksum, digest + "  " + output.name + "\n"),
                          (report_path, json.dumps(report, indent=2) + "\n")]:
        with path.open("x") as stream:
            os.chmod(path, 0o600)
            stream.write(content)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-backup", type=Path, required=True)
    parser.add_argument("--firmware-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stock-sha256", help="Known checksum recorded when the stock backup was made")
    args = parser.parse_args()
    try:
        report = prepare(args.stock_backup, args.firmware_dir, args.output, args.stock_sha256)
    except (ValueError, OSError) as error:
        parser.exit(1, "Verification failed: " + str(error) + "\n")
    print(json.dumps(report, indent=2))
    print("Keep this full image private. This command did not flash a device.")


if __name__ == "__main__":
    main()
