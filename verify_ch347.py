from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path


def default_dll_path() -> Path:
    local = Path(__file__).resolve().parent / "drivers" / "CH347DLLA64.DLL"
    if local.exists():
        return local
    return Path("CH347DLLA64")


class _SpiConfig(ctypes.Structure):
    """Maps to mSpiCfgS in CH347DLL_EN.H (#pragma pack(1))."""
    _pack_ = 1
    _fields_ = [
        ("iMode", ctypes.c_uint8),
        ("iClock", ctypes.c_uint8),
        ("iByteOrder", ctypes.c_uint8),
        ("iSpiWriteReadInterval", ctypes.c_uint16),
        ("iSpiOutDefaultData", ctypes.c_uint8),
        ("iChipSelect", ctypes.c_uint32),
        ("CS1Polarity", ctypes.c_uint8),
        ("CS2Polarity", ctypes.c_uint8),
        ("iIsAutoDeativeCS", ctypes.c_uint16),
        ("iActiveDelay", ctypes.c_uint16),
        ("iDelayDeactive", ctypes.c_uint32),
    ]


def configure_signatures(dll) -> None:
    dll.CH347OpenDevice.argtypes = [ctypes.c_ulong]
    dll.CH347OpenDevice.restype = ctypes.c_void_p
    dll.CH347CloseDevice.argtypes = [ctypes.c_ulong]
    dll.CH347CloseDevice.restype = ctypes.c_bool
    dll.CH347SPI_Init.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
    dll.CH347SPI_Init.restype = ctypes.c_bool
    dll.CH347StreamSPI4.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    dll.CH347StreamSPI4.restype = ctypes.c_bool


# iClock values from CH347DLL_EN.H:
# 0=60MHz, 1=30MHz, 2=15MHz, 3=7.5MHz, 4=3.75MHz, 5=1.875MHz, 6=937.5KHz, 7=468.75KHz
_CLOCK_LABELS = {0: "60MHz", 1: "30MHz", 2: "15MHz", 3: "7.5MHz",
                 4: "3.75MHz", 5: "1.875MHz", 6: "937.5KHz", 7: "468.75KHz"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CH347 DLL, device open, SPI init, and SPI stream call.")
    parser.add_argument("--dll", default=str(default_dll_path()), help="Path/name of CH347DLLA64.DLL")
    parser.add_argument("--index", type=int, default=0, help="CH347 device index")
    parser.add_argument("--chip-select", type=lambda s: int(s, 0), default=0x80, help="CH347 chip-select value, e.g. 0x80")
    parser.add_argument("--spi-clock", type=int, default=3, choices=range(8),
                        help="SPI clock index: 0=60MHz 1=30MHz 2=15MHz 3=7.5MHz(default) 4=3.75MHz 5=1.875MHz 6=937.5KHz 7=468.75KHz")
    parser.add_argument("--payload", default="414c504b", help="Hex bytes to clock through SPI, default is ALPK magic")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("FAIL: CH347DLLA64.DLL verification must run on Windows.")
        return 2

    dll_path = Path(args.dll)
    print(f"[1/4] Loading DLL: {dll_path}")
    try:
        dll = ctypes.WinDLL(str(dll_path))
    except OSError as exc:
        print(f"FAIL: DLL load failed: {exc}")
        return 1
    configure_signatures(dll)
    print("PASS: DLL loaded")

    index = max(0, int(args.index))
    print(f"[2/4] Opening CH347 device index={index}")
    handle = dll.CH347OpenDevice(ctypes.c_ulong(index))
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, 0, invalid):
        print("FAIL: CH347OpenDevice failed. Check USB connection, driver installation, and device mode.")
        return 1
    print(f"PASS: CH347OpenDevice handle={handle}")

    try:
        clock_label = _CLOCK_LABELS.get(args.spi_clock, str(args.spi_clock))
        print(f"[3/4] Calling CH347SPI_Init iClock={args.spi_clock} ({clock_label})")
        cfg = _SpiConfig(
            iMode=0,
            iClock=args.spi_clock,
            iByteOrder=1,
            iSpiWriteReadInterval=0,
            iSpiOutDefaultData=0xFF,
            iChipSelect=args.chip_select,
            CS1Polarity=0,
            CS2Polarity=0,
            iIsAutoDeativeCS=1,
            iActiveDelay=0,
            iDelayDeactive=0,
        )
        ok = dll.CH347SPI_Init(ctypes.c_ulong(index), ctypes.byref(cfg))
        if not ok:
            print("FAIL: CH347SPI_Init failed. Check device mode supports SPI (Mode1/Mode2).")
            return 1
        print(f"PASS: CH347SPI_Init clock={clock_label}")

        try:
            payload = bytes.fromhex(args.payload)
        except ValueError:
            print("FAIL: --payload must be hex bytes, e.g. 414c504b")
            return 1
        if not payload:
            print("FAIL: payload is empty")
            return 1

        print(f"[4/4] Calling CH347StreamSPI4 cs=0x{args.chip_select:X}, len={len(payload)}")
        buf = ctypes.create_string_buffer(payload, len(payload))
        ok = dll.CH347StreamSPI4(
            ctypes.c_ulong(index),
            ctypes.c_ulong(int(args.chip_select)),
            ctypes.c_ulong(len(payload)),
            buf,
        )
        if not ok:
            print("FAIL: CH347StreamSPI4 returned false. Check SPI wiring, CS value, and device mode.")
            return 1
        print(f"PASS: CH347StreamSPI4 returned success, rx/echo={bytes(buf.raw).hex(' ')}")
        print("RESULT: CH347 DLL load, open, SPI init, and SPI stream call all passed.")
        return 0
    finally:
        closed = dll.CH347CloseDevice(ctypes.c_ulong(index))
        print(f"Closed device: {bool(closed)}")


if __name__ == "__main__":
    raise SystemExit(main())
