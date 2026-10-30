# ThinkSmart View Root Android — v0.2.0 脱敏合成镜像

用于 Lenovo ThinkSmart View **CD-18781Y、8 GB eMMC**。基底 Android 8.1 / `Lenovo_Kingston_OS_PV_220620_V0.0.40`，Magisk 30.7（30700），原生顶栏修复为 24dp（默认 36 像素）。

## 下载与镜像性质

[下载 v0.2.0 预发布完整包及校验文件](https://github.com/lzl51230/thinksmart-view-android-rooted/releases/tag/v0.2.0)。

本次提供**单个 7,818,182,656 字节的完整尺寸脱敏合成镜像 `template.img`**，不再需要分别下载和组合四个分区文件。归档中同时提供元数据、补齐工具、官方 Magisk APK 与对应源码。

**公开模板不能直接刷入设备。必须先用目标设备自己的原厂整机备份补齐，生成该机专用的完整恢复镜像。**

公开模板只保留：

- 已验证的 boot、system、vendor、recovery 固件内容，与 v0.1.0 完全相同。
- 新生成的保护 MBR 和主备 GPT；磁盘及分区 GUID 为项目统一生成的标识，不保留来源设备 GUID。

其他所有分区、未分配区域及间隙均为零，包括 userdata、persist、密钥相关区和引导链等未列入白名单的区域。它不会携带来源设备的账号、Wi-Fi 凭据、校准或密钥。补齐工具从**目标设备自己的原厂备份**恢复这些区域和该机的原始 GPT，只替换上述四个固件分区。

Ubuntu/Linux 系统、本机未脱敏整机备份、个人签名密钥及原始设备日志均未发布。

## 文件与要求

完整包中包含 `template.img`、`template.json`、`SHA256SUMS`、Python 工具、`extras/Magisk-v30.7.apk`、匹配源码与许可说明。GitHub 的自动 Source code 包不含固件二进制。

要求：

1. 目标设备自己的原厂备份，精确大小 7,818,182,656 字节。
2. 支持的基底 boot SHA-256：`fd08fe28e0369983456d74b373dcbdcf9a60fac5a82f41cca21b555bdc3d8bac`，工具强制检查。
3. Python 3.11 或更新版本。展开模板约需 8 GB；展开后补齐时建议另有至少 12 GB 空闲空间用于私有输出和临时文件，原厂备份另行保存。
4. 实际刷写使用 USB 与 [bkerler/edl](https://github.com/bkerler/edl)，不适用于 ThinkSmart View Plus 或其他分区布局。

先使用同名 `.sha256` 校验下载归档，解压后进入套件目录。

## 验证公开模板

```sh
python3 sanitized_template.py verify --template template.img --metadata template.json
```

该命令校验完整 SHA-256、主备 GPT、四个固件分区，并逐字节检查其余区域为零。

公开模板 SHA-256：`205ff49489a927a020bb8e9e20b65099b04b43e393784bc06ef5afcdf674f80f`。

## 补齐为目标设备专用镜像

先核验原厂备份制作时记录的校验值。工具会自动读取备份旁的同名 `.sha256`，也可通过 `--stock-sha256` 显式提供；没有原始校验值时，大小、GPT 和基底 boot 校验不能证明原有用户数据本身完好。

```sh
mkdir -p out
python3 personalize_image.py --template template.img --metadata template.json --stock-backup /path/to/your-own-stock-emmc.img --output out/android-rooted-full.img
```

输入备份和公开模板保持不变。工具生成新文件，拒绝覆盖现有输出，并验证四个固件分区、主备 GPT 以及其余区域与目标机原厂备份一致。

**输出恢复的是原厂备份时的用户数据；整盘刷写会覆盖目标设备现在的数据。** 输出 `.img`、`.img.sha256` 与 `.img.json` 包含本机专属数据，只保留在本地，不要公开上传。

可独立复核生成文件或 EDL 完整回读文件：

```sh
python3 verify_restore.py --template-metadata template.json --stock-backup /path/to/your-own-stock-emmc.img --image out/android-rooted-full.img
```

## EDL 刷写与从 Linux 恢复

确认备份属于现场这台设备，保留当前系统备份，然后正常关机，按住两个音量键接通电源、连接 USB，进入 `05c6:9008` 模式。

已验证的 loader 在上游 Loaders 中为 `lenovo_motorola/000660e160008000_b9eca30dfea46934_fhprg_peek.bin`。先只读核对设备：

```sh
python3 /path/to/edl/edl.py printgpt --memory=eMMC --lun=0 --loader=/path/to/loader.bin
```

预期 APQ8053、HWID `0x000660e160008000`、512 字节扇区、15,269,888 个扇区，并核对目标机序列号。

**以下输入必须是补齐后的 `out/android-rooted-full.img`，不是公开的 `template.img`。** 核对输出 `.sha256` 后写入，并完整回读：

```sh
python3 /path/to/edl/edl.py wf out/android-rooted-full.img --memory=eMMC --lun=0 --loader=/path/to/loader.bin
python3 /path/to/edl/edl.py rs 0 15269888 out/readback.img --memory=eMMC --lun=0 --loader=/path/to/loader.bin
python3 verify_restore.py --template-metadata template.json --stock-backup /path/to/your-own-stock-emmc.img --image out/readback.img
```

回读校验值应与本地专用镜像一致。通过后断开电源，再正常开机。完整恢复包含目标机原始引导链、分区布局及其他原厂区域，可用于从 Ubuntu 布局恢复 Android。

## 首次启动、回退和验证范围

在设备上启用 USB 调试并授权电脑，安装随包提供的官方管理器：

```sh
adb -s YOUR_SERIAL install -r extras/Magisk-v30.7.apk
```

打开 Magisk，按提示修复运行环境并自动重启。root 请求按设备授权提示处理。

```sh
adb -s YOUR_SERIAL shell su -c id
python3 tools/check_statusbar.py --serial YOUR_SERIAL
```

预期 `uid=0(root)`、状态栏 36 像素且可见；检查通知下拉、快捷设置和底部导航。原设备已验证 root、界面功能和重启，SELinux 保持 Enforcing，系统分区只读。

回退使用目标设备自己的原厂整机备份，按相同 EDL 写入与完整回读校验流程恢复。

本版通过 **28 项测试**；公开模板的非白名单区域已验证全零。用真实原厂备份补齐后，结果与此前验证过的完整恢复镜像完全一致。没有执行清数据后的实刷测试，故作为预发布版本。

## 开发与旧版

```sh
python3 -m unittest discover -s tests -v
```

`sanitized_template.py build` 从已校验的四分区固件和布局源构造公开模板；它不复制来源设备的其他数据。`personalize_image.py` 仅在本地生成设备专用镜像，所有工具均不自动刷机。

[v0.1.0 四分区包](https://github.com/lzl51230/thinksmart-view-android-rooted/releases/tag/v0.1.0) 与[旧版恢复说明](docs/partition-kit-v0.1.0.md)继续保留。

自编工具采用 MIT；固件、Magisk 及其他第三方组件保留原有权利和许可，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
