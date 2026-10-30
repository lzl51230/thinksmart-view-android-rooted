#!/usr/bin/env python3
"""Recheck a private assembled image or an EDL full readback against its inputs."""
import argparse
from pathlib import Path

from firmware_tools import load_manifest, verify_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-backup", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--firmware-dir", type=Path)
    inputs.add_argument("--template-metadata", type=Path)
    parser.add_argument("--image", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.template_metadata:
            from sanitized_template import load_metadata, template_manifest
            manifest = template_manifest(load_metadata(args.template_metadata))
        else:
            manifest = load_manifest(args.firmware_dir)
        digest = verify_output(args.stock_backup, args.image, args.firmware_dir, manifest)
    except (ValueError, OSError) as error:
        parser.exit(1, "Verification failed: " + str(error) + "\n")
    print("Verified full image SHA-256: " + digest)
    print("Both GPTs are valid; only boot/system/vendor/recovery differ from your stock backup.")


if __name__ == "__main__":
    main()
