# Supplier Debug Tool Agent Instructions

## OVERVIEW

Standalone Windows-oriented PySide6 GUI for supplier-side strip debugging over Mock, Serial, or CH347 SPI transport using ALPK V1 packets.

## WHERE TO LOOK

| Task | Location | Notes |
|---|---|---|
| GUI behavior | `supplier_debug_tool/gui.py` | `MainWindow`, preview widget, stream worker |
| Protocol packets | `supplier_debug_tool/protocol.py` | ALPK header, CRC, ACK, strip frame payloads |
| Local effects | `supplier_debug_tool/effects.py` | Static preset renderer; no network dependency |
| Transports | `supplier_debug_tool/transports/` | `mock`, `serial_transport`, `ch347_spi` share `Transport` API |
| CH347 validation | `verify_ch347.py` | Loads DLL and sends SPI payload |
| Packaging | `DNTCLightDebug.spec`, `build_windows.bat`, `.github/workflows/dntc-light-debug-windows.yml` | PyInstaller Windows EXE delivery |

## CONVENTIONS

- Python dependencies are intentionally small: PySide6, pyserial, PyInstaller.
- Tool is local/offline; built-in effects should not require the FastAPI service.
- ALPK uses magic `ALPK`, 20-byte big-endian header, CRC32, ACK for control packets, no per-frame ACK.
- CH347 SPI reads require dummy clocks from host side; GUI can disable `Require ACK` for one-way board bring-up.
- `drivers/` is a local delivery/drop directory, not source.

## ANTI-PATTERNS

- Do not commit WCH DLLs, extracted driver packages, or unknown-source binary blobs.
- Do not hardcode advanced CH347 SPI mode/clock structs without confirming against supplier-provided `CH347DLL_EN.H`.
- Do not add network service dependencies to preset rendering.
- Do not block the GUI thread with continuous frame streaming or hardware I/O.

## COMMANDS

```bash
cd supplier_debug_tool
python -m pip install -r requirements.txt
python -m supplier_debug_tool
python verify_ch347.py --dll drivers\CH347DLLA64.DLL --index 0 --chip-select 0x80 --payload 414c504b
pyinstaller --noconfirm DNTCLightDebug.spec
```
