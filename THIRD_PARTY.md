# Third-party components

The MIT license in this repository covers only the original project utility code. It does not relicense the firmware images or third-party binaries.

| Component | Version / provenance | License / source |
| --- | --- | --- |
| Lenovo Android firmware | ThinkSmart View CD-18781Y, Lenovo_Kingston_OS_PV_220620_V0.0.40, Android 8.1 | Original Lenovo, Qualcomm, AOSP and included component terms remain applicable. Vendor firmware is not represented as MIT-licensed. [Lenovo support](https://support.lenovo.com/) and [AOSP](https://source.android.com/) |
| Magisk app and boot components | 30.7, official upstream release | GNU GPL v3; license in licenses/Magisk-GPL-3.0.txt; pinned upstream source snapshot included in the recovery kit. [Release](https://github.com/topjohnwu/Magisk/releases/tag/v30.7), [source tag](https://github.com/topjohnwu/Magisk/tree/v30.7) |
| Framework signing certificate | Public AOSP platform test certificate matching this firmware | [AOSP build test-key directory](https://android.googlesource.com/platform/build/+/android-8.1.0_r1/target/product/security/). No personal signing key is distributed. |
| EDL tooling | Downloaded separately by the user | [bkerler/edl](https://github.com/bkerler/edl); follow its upstream license and installation instructions. No EDL executable or loader binary is bundled. |

The Magisk APK is fetched unchanged from its official release, and its SHA-256 is recorded in manifest.json. The boot image contains the corresponding Magisk components. Lenovo firmware images are device-specific recovery artifacts; this project does not claim authorship or a blanket license over them.
