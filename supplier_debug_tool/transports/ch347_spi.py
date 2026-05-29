from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from .base import Transport, TransportError

# iClock values from CH347DLL_EN.H mSpiCfgS
# 0=60MHz, 1=30MHz, 2=15MHz, 3=7.5MHz, 4=3.75MHz, 5=1.875MHz, 6=937.5KHz, 7=468.75KHz
SPI_CLOCK_OPTIONS: list[tuple[str, int]] = [
    ("7.5 MHz", 3),
    ("3.75 MHz", 4),
    ("1.875 MHz", 5),
    ("937.5 KHz", 6),
    ("468.75 KHz", 7),
    ("15 MHz", 2),
    ("30 MHz", 1),
    ("60 MHz", 0),
]
SPI_CLOCK_DEFAULT = 3  # 7.5 MHz — safe for MCUs that accept ≤10 MHz


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


class Ch347SpiTransport(Transport):
    """CH347 SPI backend using WCH CH347DLLA64.dll.

    This backend uses CH347SPI_Init to configure the SPI clock before streaming,
    so the clock rate matches what the MCU can receive (≤10 MHz default = 7.5 MHz).
    """

    def __init__(
        self,
        dll_name: str | None = None,
        device_index: int = 0,
        chip_select: int = 0x80,
        spi_clock: int = SPI_CLOCK_DEFAULT,
    ) -> None:
        self.dll_name = (dll_name or "").strip() or str(default_dll_path())
        self.device_index = max(0, int(device_index))
        self.chip_select = int(chip_select)
        self.spi_clock = int(spi_clock)
        self._dll = None
        self._open = False

    def open(self) -> None:
        if sys.platform != "win32":
            raise TransportError("CH347 DLL backend is Windows-only")
        try:
            self._dll = ctypes.WinDLL(self.dll_name)
        except OSError as exc:
            raise TransportError(f"failed to load {self.dll_name}: {exc}") from exc

        self._configure_signatures()
        handle = self._dll.CH347OpenDevice(ctypes.c_ulong(self.device_index))
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, 0, invalid):
            raise TransportError(f"CH347OpenDevice({self.device_index}) failed")

        # Configure SPI clock — without this the CH347T defaults to ~30 MHz,
        # which exceeds the ≤10 MHz limit of the target MCU.
        cfg = _SpiConfig(
            iMode=0,
            iClock=self.spi_clock,
            iByteOrder=1,           # MSB first
            iSpiWriteReadInterval=0,
            iSpiOutDefaultData=0xFF,
            iChipSelect=self.chip_select,
            CS1Polarity=0,
            CS2Polarity=0,
            iIsAutoDeativeCS=1,     # auto de-assert CS after each transfer
            iActiveDelay=0,
            iDelayDeactive=0,
        )
        ok = self._dll.CH347SPI_Init(ctypes.c_ulong(self.device_index), ctypes.byref(cfg))
        if not ok:
            self._dll.CH347CloseDevice(ctypes.c_ulong(self.device_index))
            raise TransportError(
                f"CH347SPI_Init failed — check device mode supports SPI (Mode1/Mode2)"
            )

        self._open = True

    def close(self) -> None:
        if self._dll is not None and self._open:
            try:
                self._dll.CH347CloseDevice(ctypes.c_ulong(self.device_index))
            finally:
                self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write(self, packet: bytes) -> None:
        if self._dll is None or not self._open:
            raise TransportError("CH347 SPI transport is closed")
        buf = ctypes.create_string_buffer(bytes(packet), len(packet))
        ok = self._stream(buf, len(packet))
        if not ok:
            raise TransportError("CH347StreamSPI4 failed")

    def read(self, max_len: int, timeout_s: float) -> bytes:
        if self._dll is None or not self._open:
            raise TransportError("CH347 SPI transport is closed")
        if max_len <= 0:
            return b""
        buf = ctypes.create_string_buffer(bytes(max_len), max_len)
        ok = self._stream(buf, max_len)
        if not ok:
            raise TransportError("CH347StreamSPI4 read clock failed")
        return bytes(buf.raw)

    def _stream(self, buf, length: int) -> bool:
        if self._dll is None:
            return False
        return bool(
            self._dll.CH347StreamSPI4(
                ctypes.c_ulong(self.device_index),
                ctypes.c_ulong(self.chip_select),
                ctypes.c_ulong(length),
                buf,
            )
        )

    def _configure_signatures(self) -> None:
        if self._dll is None:
            return
        self._dll.CH347OpenDevice.argtypes = [ctypes.c_ulong]
        self._dll.CH347OpenDevice.restype = ctypes.c_void_p
        self._dll.CH347CloseDevice.argtypes = [ctypes.c_ulong]
        self._dll.CH347CloseDevice.restype = ctypes.c_bool
        self._dll.CH347SPI_Init.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
        self._dll.CH347SPI_Init.restype = ctypes.c_bool
        self._dll.CH347StreamSPI4.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        self._dll.CH347StreamSPI4.restype = ctypes.c_bool


def default_dll_path() -> Path:
    package_root = Path(__file__).resolve().parents[2]
    local_dll = package_root / "drivers" / "CH347DLLA64.DLL"
    if local_dll.exists():
        return local_dll
    return Path("CH347DLLA64")
