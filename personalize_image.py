#!/usr/bin/env python3
"""Fill a sanitized template with this target device's own stock-backup contents."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from firmware_tools import CHUNK, check_stock, require
from prepare_restore import prepare
from sanitized_template import verify_template


def personalize(template, metadata_path, stock, output, stock_sha256=None):
    template, stock, output = Path(template), Path(stock), Path(output)
    require(not output.exists(), "Refusing to overwrite an existing output")
    require(output.resolve() not in {template.resolve(), stock.resolve()},
            "Input and output must be different")
    require(output.parent.is_dir(), "Create the output directory first")
    metadata = verify_template(template, metadata_path)
    check_stock(stock, metadata)
    regions = [p for p in metadata["regions"] if p["kind"] == "firmware"]
    require(shutil.disk_usage(output.parent).free >=
            metadata["image_bytes"] + sum(p["bytes"] for p in regions),
            "Not enough free space for the private image and temporary firmware")
    with tempfile.TemporaryDirectory(prefix="thinksmart-personalize-", dir=output.parent) as work:
        directory = Path(work)
        images = []
        with template.open("rb") as source:
            for region in regions:
                source.seek(region["start"])
                filename = region["partition"] + ".img"
                with (directory / filename).open("xb") as destination:
                    remaining = region["bytes"]
                    while remaining:
                        block = source.read(min(CHUNK, remaining))
                        require(bool(block), "Template ended unexpectedly")
                        destination.write(block)
                        remaining -= len(block)
                images.append({"partition": region["partition"], "file": filename,
                               "bytes": region["bytes"], "sha256": region["sha256"]})
        manifest = {
            "schema_version": 1, "release": metadata["release"],
            "sector_size": metadata["sector_size"], "image_bytes": metadata["image_bytes"],
            "stock_boot_sha256": metadata["stock_boot_sha256"],
            "layout": metadata["layout"], "images": images,
        }
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        report = prepare(stock, directory, output, stock_sha256)
    report["source_public_template_sha256"] = metadata["sha256"]
    report["target_device_gpt_and_other_regions_restored_from_own_backup"] = True
    Path(str(output) + ".json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--stock-backup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stock-sha256")
    args = parser.parse_args()
    try:
        report = personalize(args.template, args.metadata, args.stock_backup,
                             args.output, args.stock_sha256)
    except (ValueError, OSError) as error:
        parser.exit(1, "Personalization failed: " + str(error) + "\n")
    print(json.dumps(report, indent=2))
    print("Only this PRIVATE output may be flashed to its matching target device.")
    print("The public template must not be flashed directly.")


if __name__ == "__main__":
    main()
