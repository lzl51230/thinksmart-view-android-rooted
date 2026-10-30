#!/usr/bin/env python3
"""Read only the four public firmware partitions from the authorized Android device."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess

from firmware_tools import digest_file, require

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--adb", default="adb")
parser.add_argument("--serial", required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--magisk-apk", type=Path, required=True)
args = parser.parse_args()
base = [args.adb, "-s", args.serial]


def shell(command, root=False, timeout=120):
    if root:
        command = "su -c " + shlex.quote(command)
    result = subprocess.run(base + ["shell", command], capture_output=True, text=True, timeout=timeout)
    result.check_returncode()
    return result.stdout.strip()


require(shell("id -u", True) == "0", "Root access is required for read-only export")
require(shell("getprop ro.product.device") == "msm8x53_som", "Unexpected Android device")
build = shell("getprop ro.build.display.id")
require(build == "Lenovo_Kingston_OS_PV_220620_V0.0.40", "Unsupported firmware build")
require(shell("magisk -V", True) == "30700", "Expected Magisk 30.7")
require(shell("cat /sys/class/block/mmcblk0/size", True) == "15269888", "Unexpected eMMC capacity")
mounts = shell("cat /proc/mounts").splitlines()
for mountpoint in ["/system", "/vendor"]:
    require(any(len(line.split()) > 3 and line.split()[1] == mountpoint and
                "ro" in line.split()[3].split(",") for line in mounts),
            mountpoint + " must be mounted read-only")
framework_sha = shell("sha256sum /system/framework/framework-res.apk", True).split()[0]
require(framework_sha == "6326af13f272d6d263e224ecd8ec5eadb5733476216df9320222e6b1df591dc2",
        "The expected status-bar framework fix is not installed")
require(not args.output.exists(), "Output directory already exists")
require(digest_file(args.magisk_apk) ==
        "e0d32d2123532860f97123d927b1bb86c4e08e6fd8a48bfc6b5bee0afae9ebd5",
        "Unexpected Magisk APK")
args.output.mkdir(parents=True)
(args.output / "images").mkdir()
(args.output / "extras").mkdir()
layout = json.loads((Path(__file__).parent / "firmware/android-layout.json").read_text())
by_name = {entry["name"]: entry for entry in layout}
images = []
for name in ["boot", "system", "vendor", "recovery"]:
    partition = by_name[name]
    expected_size = partition["sectors"] * 512
    block = "/dev/block/bootdevice/by-name/" + name
    print("Exporting " + name + " (" + str(expected_size) + " bytes)", flush=True)
    temporary = args.output / ("images/" + name + ".img.partial")
    final = args.output / ("images/" + name + ".img")
    with temporary.open("xb") as stream:
        result = subprocess.run(base + ["exec-out", "su -c " + shlex.quote("cat " + block)],
                                stdout=stream, stderr=subprocess.PIPE, timeout=900)
    require(result.returncode == 0, "ADB partition export failed: " + name)
    require(temporary.stat().st_size == expected_size, "Partition export is incomplete: " + name)
    local_sha = digest_file(temporary)
    remote_sha = shell("sha256sum " + block, True).split()[0]
    require(local_sha == remote_sha, "Host/device checksum mismatch: " + name)
    temporary.rename(final)
    images.append({"partition": name, "file": "images/" + name + ".img",
                   "bytes": expected_size, "sha256": local_sha})
    print("Verified " + name + ": " + local_sha, flush=True)
require(images[0]["sha256"] ==
        "b92c0b7cca746f75ea6cc6adb74ca18231948ebcbc451302eaaba6e1ea207c72",
        "The exported boot is not the verified rooted boot")
apk_name = "extras/Magisk-v30.7.apk"
shutil.copyfile(args.magisk_apk, args.output / apk_name)
manifest = {
    "schema_version": 1, "release": "v0.1.0",
    "device_model": "Lenovo ThinkSmart View CD-18781Y",
    "android_version": "8.1.0", "firmware_build": build,
    "root": "Magisk 30.7 (30700)", "status_bar_dp": 24,
    "sector_size": 512, "image_bytes": 7818182656,
    "stock_boot_sha256": "fd08fe28e0369983456d74b373dcbdcf9a60fac5a82f41cca21b555bdc3d8bac",
    "framework_sha256": framework_sha, "layout": layout, "images": images,
    "extras": [{"file": apk_name, "sha256": digest_file(args.output / apk_name),
                "source": "https://github.com/topjohnwu/Magisk/releases/tag/v30.7"}],
}
(args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Read-only firmware export complete.", flush=True)
