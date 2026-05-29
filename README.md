# DNTC Light Debug Tool

一个独立的 Windows 灯带调试工具项目，用于给供应商调试 USB → CH347 → SPI/串口 → 灯效开发板链路。

当前版本重点支持：

- GUI 操作灯带调试；
- 内置本地静态预设灯效算法；
- ALPK V1 协议封包；
- HELLO / START_STREAM 握手；
- 亮度、开关、模式指令；
- 灯带 RGB24 帧流；
- Mock 传输、串口传输；
- 后续可接入 CH347 SPI DLL 传输。

## 运行

```bash
cd supplier_debug_tool
python -m pip install -r requirements.txt
python -m supplier_debug_tool
```

## 打包 EXE

### 推荐：Windows 一键打包

不接入硬件也可以先打包：

```bat
build_windows.bat
```

它会依次执行：

1. 安装 `requirements.txt`
2. 跳过硬件验证
3. 用 PyInstaller 打包 exe

如果已接入 CH347，并希望打包前强制验证硬件：

```bat
build_windows.bat --verify-hardware
```

此模式会在打包前运行 `verify_ch347.py` 验证：

- `CH347DLLA64.DLL` 是否能加载
- `CH347OpenDevice(0)` 是否成功
- `CH347StreamSPI4(...)` 是否返回成功

如果只想单独验证 CH347：

```bat
python verify_ch347.py
```

可选参数示例：

```bat
python verify_ch347.py --dll drivers\CH347DLLA64.DLL --index 0 --chip-select 0x80 --payload 414c504b
```

`payload=414c504b` 即 ASCII `ALPK`，便于用逻辑分析仪/示波器确认 MOSI 输出。

### 手动打包

```bash
cd supplier_debug_tool
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --onefile --windowed --name DNTCLightDebug supplier_debug_tool\__main__.py
```

或使用仓库内置 spec：

```bash
pyinstaller --noconfirm DNTCLightDebug.spec
```

生成文件：

```text
dist/DNTCLightDebug.exe
```

## 传输方式

### Mock

不连接硬件，只在日志窗口显示发送行为，用于 GUI 和协议自测。

### Serial

通过 pyserial 打开串口设备并写入 ALPK 包。适合 CH347 VCP/串口桥接调试，或供应商板先用串口口径验证协议。

### CH347 SPI DLL

接口：`supplier_debug_tool/transports/ch347_spi.py`。

当前实现使用经公开头文件/示例确认的基础函数：

- `CH347OpenDevice`
- `CH347CloseDevice`
- `CH347StreamSPI4`

高级 SPI 初始化参数与不同 DLL 版本、供应商驱动包有关，暂不写死。若开发板要求特定 SPI mode/clock，需要用供应商提供的 `CH347DLL_EN.H` 补充配置结构。

SPI 是主机主动时钟：ACK/HELLO_ACK 读取通过发送 dummy clocks 完成。如果开发板暂未实现 SPI 回读，可在 GUI 里取消 `Require ACK` 先做单向下发验证。

### 官方 DLL / 驱动放置方式

如果使用 `CH347 SPI DLL` 后端，需要供应商或调试电脑具备 WCH 官方 CH347/CH341PAR 驱动与 DLL。建议从 WCH 官网下载对应驱动包，例如：

```text
https://www.wch.cn/downloads/category/67.html
```

当前本地交付目录已按官方 `CH341PAR.ZIP` 提取必要文件到：

```text
supplier_debug_tool/drivers/CH347DLLA64.DLL
supplier_debug_tool/drivers/CH347DLL_EN.H
```

`drivers/` 目录只用于供应商本地调试交付，已加入根 `.gitignore`，不要上传 GitHub。

推荐两种部署方式：

1. **安装官方驱动包**：安装后 Windows 可从系统路径加载 `CH347DLLA64.dll`，GUI 中 DLL 字段保持默认 `CH347DLLA64`。
2. **随 exe 放置 DLL**：将官方包里的 `CH347DLLA64.DLL` 放到 `DNTCLightDebug.exe` 同目录，或放到 `drivers/` 目录。GUI 默认会优先使用本项目 `drivers/CH347DLLA64.DLL`。

不建议把未知来源 DLL 提交进源码仓库；如果要随安装包分发，应先确认 WCH 驱动/DLL 的授权条款。

若要把 DLL 打进 PyInstaller 产物，可在 Windows 打包机上使用：

```bash
pyinstaller --noconfirm --onefile --windowed \
  --name DNTCLightDebug \
  --add-binary "drivers/CH347DLLA64.dll;." \
  supplier_debug_tool/__main__.py
```

## 协议

工具使用 ALPK V1 二进制调试协议：

- PacketHeaderV1：20B，magic=`ALPK`，Big-Endian；
- 控制包需要 ACK；
- 帧包不逐帧 ACK；
- 灯带帧使用 `MSG_STRIP_FRAME = 0x21`；
- Strip payload：`frame_id/channel_id/led_count/duration_ms/rgb_len + RGB24`。

`STRIP_FRAME` payload 字节结构：

| Offset | Size | 字段 | 说明 |
|---:|---:|---|---|
| 0 | 4 | `frame_id` | 递增帧号，Big-Endian |
| 4 | 2 | `channel_id` | 灯带通道 |
| 6 | 2 | `led_count` | LED 数量 |
| 8 | 4 | `duration_ms` | 本帧建议显示时长 |
| 12 | 4 | `rgb_len` | `led_count * 3` |
| 16 | `rgb_len` | `rgb` | `led[0].R,G,B ... led[N-1].R,G,B` |

本工具内置的灯效均为本地静态算法，不依赖网络服务；当前只实现灯带调试。

## 建议联调顺序

1. 使用 Mock 模式确认 GUI、指令和帧流；
2. 使用 Serial 模式确认开发板 ALPK 解析；
3. 接入 CH347 SPI DLL，替换 transport；
4. 再打开连续灯效流。
