# DNTC Light Debug Tool 使用说明

## 1. 用途

本工具用于调试 DNTC 氛围灯开发板。

电脑通过 USB 连接 CH347，再由 CH347 输出 SPI 数据到开发板。工具内置了几种灯带测试效果，可用于确认接线、通信和灯效显示是否正常。

## 2. 启动

双击运行：

```text
DNTCLightDebug.exe
```

正常情况下不需要单独放 DLL。程序已经随包携带 CH347 需要的 DLL。

如果启动或连接时提示 DLL 加载失败，请先确认电脑已安装 WCH 官方 CH347 驱动，或联系 DNTC 重新确认打包文件。

## 3. 连接设置

### Backend

默认选择：

```text
CH347 SPI DLL
```

这是正式调试 CH347 SPI 的模式。
其他模式：

- `Mock`：不接硬件，只验证软件界面和协议流程。
- `Serial`：通过 COM 串口发送数据，通常只用于临时调试。

### Device Index

电脑只接一个 CH347 时保持：

```text
0
```

如果同时接了多个 CH347，才需要改成 `1`、`2` 等。

### Chip Select

默认保持：

```text
0x80
```

它表示 CH347 使用哪一路 SPI 片选线。只有开发板接到其他 CS 引脚时才需要修改。

### Reliable Control

建议保持勾选。
它表示关键控制指令需要开发板回复确认，例如握手、开始推流、亮度、开关、模式设置。灯效帧本身不会逐帧确认，避免影响速度。
如果开发板暂时没有实现 SPI 回读 ACK，可以临时取消勾选，用于先验证单向发送和灯效显示。

## 4. Channel 对应关系

软件中的 Channel 表示灯带通道：

| Channel | 位置 |
|---|---|
| `strip:1` | 仪表台长灯带 |
| `strip:2` | 左前门灯带 |
| `strip:3` | 左后门灯带 |
| `strip:4` | 右前门灯带 |
| `strip:5` | 右后门灯带 |

供应商调试时请保持通道和实车位置一致，不要按接线顺序随意交换。

## 5. 基本操作

1. 连接 CH347 和开发板，并确认共地。
2. 打开 `DNTCLightDebug.exe`。
3. Backend 保持 `CH347 SPI DLL`。
4. 点击 `Connect`。
5. 点击 `Handshake`。
6. 选择 Channel、LED Count、FPS、Brightness 和 Preset。
7. 点击 `Start Stream` 开始发送灯效。
8. 点击 `Stop Stream` 停止发送。

如果连接失败，先点击 `Diagnostics`，把日志窗口里的串口列表、DLL 加载结果、CH347OpenDevice 结果截图发给 DNTC。

常用建议：

- `FPS`：先用 30。
- `Brightness`：先用 0.3 到 0.8。
- `LED Count`：填写当前通道实际灯珠数量。

## 6. 常见问题

### Connect 失败

检查 CH347 是否插好，驱动是否安装，是否被其他软件占用。

### 有波形但灯不亮

检查 SPI 接线、GND、CS、灯带供电、灯珠数量和开发板协议解析。

### Handshake 失败

如果开发板还没有实现回读 ACK，可先取消 `Reliable Control` 再测试。

### 灯效颜色不对

确认开发板按 RGB 顺序解析。如果开发板使用 GRB，需要在开发板侧或协议适配层转换。

### 速度不稳定

先降低 FPS 或 LED Count，确认链路稳定后再提高。
如需重新打包或更换 DLL，请联系 DNTC。
