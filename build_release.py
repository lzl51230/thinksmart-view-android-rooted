#!/usr/bin/env python3
"""Package only the explicit public firmware and source allowlist."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

from firmware_tools import digest_file, load_manifest, require

PUBLIC_FILES = [
    "README.md", "LICENSE", "THIRD_PARTY.md", "firmware_tools.py",
    "prepare_restore.py", "verify_restore.py", "export_firmware.py", "build_release.py",
    "tools/check_statusbar.py", "tools/patch_framework.py",
    "firmware/android-layout.json", "licenses/Magisk-GPL-3.0.txt", "tests/test_restore.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware-dir", type=Path, required=True)
    parser.add_argument("--magisk-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    kit = args.firmware_dir.resolve()
    require(not args.output.exists(), "Release archive already exists")
    manifest = load_manifest(kit)
    source_name = "extras/Magisk-v30.7-source.tar.gz"
    require(args.magisk_source.is_file(), "Missing upstream Magisk source archive")
    with tarfile.open(args.magisk_source, "r:gz") as archive:
        require(all(p.name.startswith("Magisk-30.7/") or p.name == "Magisk-30.7"
                    for p in archive.getmembers()), "Unexpected Magisk source archive layout")
    shutil.copyfile(args.magisk_source, kit / source_name)
    extras = {entry["file"]: entry for entry in manifest["extras"]}
    extras[source_name] = {
        "file": source_name, "sha256": digest_file(kit / source_name),
        "source": "https://github.com/topjohnwu/Magisk/tree/v30.7",
    }
    manifest["extras"] = list(extras.values())
    (kit / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (source / "firmware/manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in PUBLIC_FILES:
        destination = kit / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        legacy_guide = source / "docs/partition-kit-v0.1.0.md"
        if name == "README.md" and manifest["release"] == "v0.1.0" and legacy_guide.exists():
            destination.write_text(legacy_guide.read_text().replace(
                "(../THIRD_PARTY.md)", "(THIRD_PARTY.md)"))
        else:
            shutil.copyfile(source / name, destination)
    names = sorted(PUBLIC_FILES + ["manifest.json"] +
                   [entry["file"] for entry in manifest["images"]] +
                   [entry["file"] for entry in manifest["extras"]])
    require(len(names) == len(set(names)), "Duplicate release member")
    checksums = []
    for name in names:
        path = (kit / name).resolve()
        require(path.is_relative_to(kit) and path.is_file() and not (kit / name).is_symlink(),
                "Release input must be a regular file inside the kit")
        checksums.append(digest_file(path) + "  " + name + "\n")
    (kit / "SHA256SUMS").write_text("".join(checksums))
    names.append("SHA256SUMS")
    root_name = "thinksmart-view-cd18781y-android8.1-rooted-v0.1.0"
    partial = Path(str(args.output) + ".partial")
    require(not partial.exists(), "An unfinished release archive already exists")
    print("Compressing public release (" + str(len(names)) + " files)", flush=True)
    try:
        with partial.open("xb") as output:
            process = subprocess.Popen(["xz", "-T2", "-4", "--stdout"],
                                       stdin=subprocess.PIPE, stdout=output)
            try:
                with tarfile.open(fileobj=process.stdin, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                    for name in names:
                        path = kit / name
                        info = tarfile.TarInfo(root_name + "/" + name)
                        info.size = path.stat().st_size
                        info.mode = 0o644
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mtime = 0
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                process.stdin.close()
                require(process.wait(timeout=1800) == 0, "xz compression failed")
            except BaseException:
                process.kill()
                process.wait()
                raise
            output.flush()
            os.fsync(output.fileno())
        require(partial.stat().st_size < 2 * 1024 ** 3, "Release asset exceeds GitHub's 2 GiB limit")
        partial.rename(args.output)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    checksum = digest_file(args.output)
    Path(str(args.output) + ".sha256").write_text(checksum + "  " + args.output.name + "\n")
    (source / "firmware/release-files.json").write_text(json.dumps({
        "archive": args.output.name, "bytes": args.output.stat().st_size,
        "sha256": checksum, "members": sorted(names),
        "tar_owner_metadata": "uid/gid 0, empty user/group names, mtime 0",
    }, indent=2) + "\n")
    print(json.dumps({"archive": args.output.name, "bytes": args.output.stat().st_size,
                      "sha256": checksum}, indent=2), flush=True)


if __name__ == "__main__":
    main()
