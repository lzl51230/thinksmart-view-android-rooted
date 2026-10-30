# ThinkSmart View Root Android Recovery Kit

联想 ThinkSmart View **CD-18781Y（8 GB eMMC）** 的 Android 8.1 完整恢复工具与固件。当前版本 **v0.1.0，预发布**。

- 基底：`Lenovo_Kingston_OS_PV_220620_V0.0.40`。
- Root：Magisk 30.7（30700），官方 APK、许可和匹配源码随发布包提供。
- 原生状态栏：从 `0dp` 修复为 `24dp`，默认 240 dpi 下为 36 像素。
- 本机已验证：root、重启、状态栏、通知下拉、快捷设置及底部导航。

固件来自已验证设备。完整恢复工具完成离线镜像合成和校验；**本发布未进行清数据后的完整实刷测试**。不适用于 ThinkSmart View Plus 或其他存储布局。

## 下载内容

从 [Releases](https://github.com/lzl51230/thinksmart-view-android-rooted/releases/tag/v0.1.0) 下载完整 `.tar.xz` 包及同名 `.sha256`。Git 仓库和 GitHub 自动生成的 Source code 包只包含工具与文档，不含固件镜像。

完整包包含：

| 文件 | 用途 |
| --- | --- |
| `images/boot.img` | 已验证的 Magisk 启动镜像，32 MiB |
| `images/system.img` | 已修复原生状态栏的 Android 系统分区，1536 MiB |
| `images/vendor.img` | 匹配的原厂 vendor 分区，384 MiB |
| `images/recovery.img` | 匹配的原厂 recovery，32 MiB |
| `extras/Magisk-v30.7.apk` | 首次启动后的管理器安装及运行环境初始化 |
| `extras/Magisk-v30.7-source.tar.gz` | 对应版本的上游源码快照 |
| `manifest.json`、`SHA256SUMS` | 版本、分区布局、大小与 SHA-256 |
| Python 工具和说明 | 合成及验证完整恢复镜像 |

发布内容不包括 Ubuntu 系统、原始整机备份、userdata、persist、设备密钥、Wi-Fi 凭据或原始设备日志。各镜像的精确校验值见 `manifest.json`。

## 必需条件

1. **目标设备自己的原厂整机备份**，大小为 7,818,182,656 字节。不能使用其他设备的整机备份。
2. 先核验原厂备份在生成时记录的 SHA-256。工具会自动读取同名 `.sha256` 文件，也支持 `--stock-sha256` 显式传入；没有原始校验值时只能检查大小、GPT 和基底 boot，不能证明用户数据原本完好。
3. 基底 boot SHA-256 必须为 `fd08fe28e0369983456d74b373dcbdcf9a60fac5a82f41cca21b555bdc3d8bac`；工具会强制检查，以排除未验证的固件版本。
4. Python 3.11 或更新版本，以及约 10 GB 可用空间。
5. 实际刷写时需要 USB 数据线、Qualcomm EDL 及 [bkerler/edl](https://github.com/bkerler/edl)。该机的普通 fastboot 刷写受锁限制，本流程使用 EDL。

## 从原厂备份合成完整恢复镜像

先校验下载归档的 `.sha256`，解压后进入套件目录，再校验内部文件：

```sh
sha256sum -c SHA256SUMS
```

macOS 可使用 `shasum -a 256 -c SHA256SUMS`。准备输出目录，然后运行：

```sh
mkdir -p out
python3 prepare_restore.py --stock-backup /path/to/your-own-stock-emmc.img --firmware-dir . --output out/android-rooted-full.img
```

工具会校验文件、主备 GPT、51 个分区布局和基底 boot 指纹，复制你的备份，再只替换 boot、system、vendor、recovery。设备校准、密钥、GPT GUID 及其他区域全部沿用**你自己的备份**，并逐段比较未替换区域。输入备份保持不变，已有输出文件会被拒绝覆盖。

输出包括完整镜像、`.sha256` 和 `.json` 校验记录。这些文件包含你自己的设备和用户数据，**只保留在本地，不要上传 GitHub**。

可再次独立核验：

```sh
python3 verify_restore.py --stock-backup /path/to/your-own-stock-emmc.img --firmware-dir . --image out/android-rooted-full.img
```

## 从 Linux 恢复 Android

这一步会将目标机当前所有分区和数据替换为合成镜像，包括用原厂备份时的用户数据覆盖当前用户数据。先保留当前设备的可恢复备份，并确认原厂备份属于这台设备。

1. 正常关机，按住两个音量键接通电源并连接 USB，进入 Qualcomm `05c6:9008` 模式。
2. 安装并配置上游 EDL。已验证的 loader 位于其 Loaders 仓库：`lenovo_motorola/000660e160008000_b9eca30dfea46934_fhprg_peek.bin`。
3. 先只读检查设备。预期 HWID 为 `0x000660e160008000`、APQ8053、512 字节扇区、15,269,888 个扇区；同时核对现场连接设备的序列号。

```sh
python3 /path/to/edl/edl.py printgpt --memory=eMMC --lun=0 --loader=/path/to/loader.bin
```

4. 再核验本地完整镜像的 `.sha256`，确认一致后写入：

```sh
python3 /path/to/edl/edl.py wf out/android-rooted-full.img --memory=eMMC --lun=0 --loader=/path/to/loader.bin
```

5. 保持 EDL，回读完整用户区：

```sh
python3 /path/to/edl/edl.py rs 0 15269888 out/android-rooted-readback.img --memory=eMMC --lun=0 --loader=/path/to/loader.bin
python3 verify_restore.py --stock-backup /path/to/your-own-stock-emmc.img --firmware-dir . --image out/android-rooted-readback.img
```

回读 SHA-256 应与合成镜像一致。**校验通过后**断开电源，正常重新开机。分区表、vendor、recovery 及设备专属分区均来自完整合成镜像，因此可恢复被 Ubuntu 扩展分区覆盖的 Android 布局。

## 首次启动与检查

如果目标设备尚未授权这台电脑，先在设备上启用 USB 调试并确认授权。安装随包提供的官方管理器：

```sh
adb -s YOUR_SERIAL install -r extras/Magisk-v30.7.apk
```

打开 Magisk，完成它提示的运行环境修复和自动重启。后续 root 请求按设备上的授权提示处理。

```sh
adb -s YOUR_SERIAL shell su -c id
python3 tools/check_statusbar.py --serial YOUR_SERIAL
```

预期 root 为 `uid=0(root)`，状态栏高度为 36、显示表面可见。检查通知下拉、快捷设置和导航键；系统分区应只读挂载，SELinux 应为 Enforcing。

## 回退与源码

完整回退使用你自己的原厂整机备份，通过相同 EDL 写入、完整回读和校验流程恢复。

`tools/patch_framework.py` 可验证原框架 SHA-256，并只修改既有 `android:dimen/status_bar_height`；其输出为**未签名 APK**，需要使用与目标框架匹配的签名并由 root 部署。发布包中的已修复框架使用与本固件相同的公开 AOSP 平台测试证书。个人签名密钥不随项目发布。

Root 镜像按 [Magisk 镜像修补流程](https://topjohnwu.github.io/Magisk/install.html) 在本机原始 boot 上生成，保留原内核、设备树与内核命令行，使用 `KEEPVERITY=true`、`KEEPFORCEENCRYPT=true`。上游建议在目标设备上修补其自己的 boot；本项目的预构建镜像仅覆盖上述严格匹配的基底。

开发验证：

```sh
python3 -m unittest discover -s tests -v
```

只读导出工具 `export_firmware.py` 需要明确指定 ADB 设备、输出目录和官方 Magisk APK，会读取并校验四个允许发布的分区。输出固件放在 Git 忽略的 `dist/` 下。项目不自动执行刷机、清数据或仓库发布。

## 许可

本仓库自编 Python 工具采用 MIT；固件、Magisk 和其他第三方组件保留各自权利与原有许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)。MIT 许可不覆盖 Lenovo 固件或 Magisk 二进制。
