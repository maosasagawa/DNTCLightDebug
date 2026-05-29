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


def configure_signatures(dll) -> None:
    dll.CH347OpenDevice.argtypes = [ctypes.c_ulong]
    dll.CH347OpenDevice.restype = ctypes.c_void_p
    dll.CH347CloseDevice.argtypes = [ctypes.c_ulong]
    dll.CH347CloseDevice.restype = ctypes.c_bool
    dll.CH347StreamSPI4.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    dll.CH347StreamSPI4.restype = ctypes.c_bool


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CH347 DLL, device open, and SPI stream call.")
    parser.add_argument("--dll", default=str(default_dll_path()), help="Path/name of CH347DLLA64.DLL")
    parser.add_argument("--index", type=int, default=0, help="CH347 device index")
    parser.add_argument("--chip-select", type=lambda s: int(s, 0), default=0x80, help="CH347 chip-select value, e.g. 0x80")
    parser.add_argument("--payload", default="414c504b", help="Hex bytes to clock through SPI, default is ALPK magic")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("FAIL: CH347DLLA64.DLL verification must run on Windows.")
        return 2

    dll_path = Path(args.dll)
    print(f"[1/3] Loading DLL: {dll_path}")
    try:
        dll = ctypes.WinDLL(str(dll_path))
    except OSError as exc:
        print(f"FAIL: DLL load failed: {exc}")
        return 1
    configure_signatures(dll)
    print("PASS: DLL loaded")

    index = max(0, int(args.index))
    print(f"[2/3] Opening CH347 device index={index}")
    handle = dll.CH347OpenDevice(ctypes.c_ulong(index))
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, 0, invalid):
        print("FAIL: CH347OpenDevice failed. Check USB connection, driver installation, and device mode.")
        return 1
    print(f"PASS: CH347OpenDevice handle={handle}")

    try:
        try:
            payload = bytes.fromhex(args.payload)
        except ValueError:
            print("FAIL: --payload must be hex bytes, e.g. 414c504b")
            return 1
        if not payload:
            print("FAIL: payload is empty")
            return 1

        print(f"[3/3] Calling CH347StreamSPI4 cs=0x{args.chip_select:X}, len={len(payload)}")
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
        print("RESULT: CH347 DLL load, open, and SPI stream call all passed.")
        return 0
    finally:
        closed = dll.CH347CloseDevice(ctypes.c_ulong(index))
        print(f"Closed device: {bool(closed)}")


if __name__ == "__main__":
    raise SystemExit(main())
