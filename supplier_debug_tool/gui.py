from __future__ import annotations

import sys
import time
import ctypes
from pathlib import Path

try:
    from serial.tools import list_ports
except Exception:  # pragma: no cover - pyserial is optional until Serial backend is used
    list_ports = None

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import protocol
from .client import DebugClient
from .effects import PRESETS, EffectPreset, preset_by_key, render_preset
from .transports import Ch347SpiTransport, MockTransport, SerialTransport, Transport, TransportError
from .transports.ch347_spi import SPI_CLOCK_DEFAULT, SPI_CLOCK_OPTIONS, default_dll_path


class StripPreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._frame: list[tuple[int, int, int]] = []
        self.setMinimumHeight(70)

    def set_frame(self, frame: list[tuple[int, int, int]]) -> None:
        self._frame = frame
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 22, 26))
        if not self._frame:
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(self.rect(), 0x84, "No frame")
            return
        margin = 10
        usable_w = max(1, self.width() - margin * 2)
        y = self.height() // 2
        step = usable_w / max(1, len(self._frame))
        radius = max(3, min(10, int(step / 2)))
        for i, (r, g, b) in enumerate(self._frame):
            x = int(margin + i * step + step / 2)
            painter.setBrush(QColor(r, g, b))
            painter.setPen(QColor(45, 45, 45))
            painter.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)


class StreamWorker(QObject):
    log = Signal(str)
    preview = Signal(list)
    stopped = Signal()
    failed = Signal(str)

    def __init__(self, client: DebugClient, preset: EffectPreset, led_count: int, fps: int, brightness: float, speed: float, channel_id: int) -> None:
        super().__init__()
        self.client = client
        self.preset = preset
        self.led_count = led_count
        self.fps = max(1, fps)
        self.brightness = brightness
        self.speed = speed
        self.channel_id = channel_id
        self._running = True

    @Slot()
    def run(self) -> None:
        duration_ms = max(1, round(1000 / self.fps))
        next_deadline = time.perf_counter()
        sent = 0
        try:
            while self._running:
                now_s = time.time()
                frame = render_preset(self.preset, led_count=self.led_count, now_s=now_s, brightness=self.brightness, speed=self.speed)
                rgb = protocol.frame_to_rgb24(frame)
                self.client.send_strip_frame(
                    channel_id=self.channel_id,
                    led_count=self.led_count,
                    duration_ms=duration_ms,
                    rgb=rgb,
                )
                sent += 1
                if sent % self.fps == 0:
                    self.log.emit(f"streaming {self.preset.name}: {sent} frames sent")
                self.preview.emit(frame)
                next_deadline += 1.0 / self.fps
                sleep_s = max(0.0, next_deadline - time.perf_counter())
                if sleep_s > 0:
                    QThread.msleep(max(1, int(sleep_s * 1000)))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.stopped.emit()

    @Slot()
    def stop(self) -> None:
        self._running = False


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DNTC Light Debug Tool")
        self.resize(980, 680)
        self.client: DebugClient | None = None
        self.transport: Transport | None = None
        self.stream_thread: QThread | None = None
        self.stream_worker: StreamWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        top.addWidget(self._connection_group(), 1)
        top.addWidget(self._strip_group(), 1)
        layout.addLayout(top)

        self.preview = StripPreview()
        layout.addWidget(self.preview)

        buttons = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_transport)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_transport)
        self.handshake_btn = QPushButton("Handshake")
        self.handshake_btn.clicked.connect(self.handshake)
        self.power_on_btn = QPushButton("Power On")
        self.power_on_btn.clicked.connect(lambda: self.set_power(True))
        self.power_off_btn = QPushButton("Power Off")
        self.power_off_btn.clicked.connect(lambda: self.set_power(False))
        self.mode_btn = QPushButton("Send Mode")
        self.mode_btn.clicked.connect(self.send_mode)
        self.diagnostics_btn = QPushButton("Diagnostics")
        self.diagnostics_btn.clicked.connect(self.run_diagnostics)
        self.start_btn = QPushButton("Start Stream")
        self.start_btn.clicked.connect(self.start_stream)
        self.stop_btn = QPushButton("Stop Stream")
        self.stop_btn.clicked.connect(self.stop_stream)
        for button in [self.connect_btn, self.disconnect_btn, self.handshake_btn, self.power_on_btn, self.power_off_btn, self.mode_btn, self.diagnostics_btn, self.start_btn, self.stop_btn]:
            buttons.addWidget(button)
        layout.addLayout(buttons)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view, 1)

        self.setCentralWidget(root)
        self._update_buttons()

    def _connection_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        form = QFormLayout(group)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["Mock", "Serial", "CH347 SPI DLL"])
        self.backend_combo.setCurrentText("CH347 SPI DLL")
        self.serial_port_combo = QComboBox()
        self.serial_port_combo.setEditable(True)
        self.refresh_ports_btn = QPushButton("Refresh")
        self.refresh_ports_btn.clicked.connect(self.refresh_serial_ports)
        serial_port_row = QHBoxLayout()
        serial_port_row.addWidget(self.serial_port_combo, 1)
        serial_port_row.addWidget(self.refresh_ports_btn)
        self.baud_spin = QSpinBox()
        self.baud_spin.setRange(1200, 12000000)
        self.baud_spin.setValue(3000000)
        self.dll_edit = QLineEdit(str(default_dll_path()))
        self.device_index_spin = QSpinBox()
        self.device_index_spin.setRange(0, 8)
        self.chip_select_spin = QSpinBox()
        self.chip_select_spin.setRange(0, 255)
        self.chip_select_spin.setValue(0x80)
        self.spi_clock_combo = QComboBox()
        for label, _ in SPI_CLOCK_OPTIONS:
            self.spi_clock_combo.addItem(label)
        default_idx = next(
            (i for i, (_, v) in enumerate(SPI_CLOCK_OPTIONS) if v == SPI_CLOCK_DEFAULT), 0
        )
        self.spi_clock_combo.setCurrentIndex(default_idx)
        self.require_ack_check = QCheckBox("Require ACK")
        self.require_ack_check.setChecked(True)
        form.addRow("Backend", self.backend_combo)
        form.addRow("Serial Port", serial_port_row)
        form.addRow("Baudrate", self.baud_spin)
        form.addRow("DLL", self.dll_edit)
        form.addRow("Device Index", self.device_index_spin)
        form.addRow("Chip Select", self.chip_select_spin)
        form.addRow("SPI Clock", self.spi_clock_combo)
        form.addRow("Reliable Control", self.require_ack_check)
        self.refresh_serial_ports(log_result=False)
        return group

    def _strip_group(self) -> QGroupBox:
        group = QGroupBox("Strip")
        form = QFormLayout(group)
        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(1, 255)
        self.channel_spin.setValue(1)
        self.led_count_spin = QSpinBox()
        self.led_count_spin.setRange(1, 2000)
        self.led_count_spin.setValue(60)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(30)
        self.brightness_spin = QDoubleSpinBox()
        self.brightness_spin.setRange(0.0, 1.0)
        self.brightness_spin.setSingleStep(0.05)
        self.brightness_spin.setValue(0.8)
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 20.0)
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(2.0)
        self.preset_combo = QComboBox()
        for preset in PRESETS:
            self.preset_combo.addItem(preset.name, preset.key)
        self.preset_combo.currentIndexChanged.connect(self.refresh_preview)
        channel_map = QLabel(
            "strip:1 Dashboard long strip; strip:2 Left front door; "
            "strip:3 Left rear door; strip:4 Right front door; strip:5 Right rear door"
        )
        channel_map.setWordWrap(True)
        form.addRow("Channel", self.channel_spin)
        form.addRow("Channel Map", channel_map)
        form.addRow("LED Count", self.led_count_spin)
        form.addRow("FPS", self.fps_spin)
        form.addRow("Brightness", self.brightness_spin)
        form.addRow("Speed", self.speed_spin)
        form.addRow("Preset", self.preset_combo)
        QTimer.singleShot(0, self.refresh_preview)
        return group

    @Slot()
    def refresh_serial_ports(self, log_result: bool = True) -> None:
        current = self._selected_serial_port()
        self.serial_port_combo.blockSignals(True)
        self.serial_port_combo.clear()
        selected_index = -1
        preferred_index = -1
        ports = [] if list_ports is None else list(list_ports.comports())
        for port in ports:
            label = self._serial_port_label(port.device, port.description, port.hwid)
            self.serial_port_combo.addItem(label, port.device)
            if current and port.device.lower() == current.lower():
                selected_index = self.serial_port_combo.count() - 1
            if preferred_index < 0 and self._is_preferred_serial_port(port.description, port.hwid):
                preferred_index = self.serial_port_combo.count() - 1
        if current and selected_index < 0:
            self.serial_port_combo.addItem(current, current)
            selected_index = self.serial_port_combo.count() - 1
        if self.serial_port_combo.count() == 0:
            self.serial_port_combo.addItem("COM3", "COM3")
            selected_index = 0
        if selected_index >= 0:
            self.serial_port_combo.setCurrentIndex(selected_index)
        elif preferred_index >= 0:
            self.serial_port_combo.setCurrentIndex(preferred_index)
        self.serial_port_combo.blockSignals(False)
        if log_result:
            self.log(f"serial ports refreshed: {len(ports)} found")

    def _selected_serial_port(self) -> str:
        data = self.serial_port_combo.currentData()
        if isinstance(data, str) and data.strip():
            return data.strip()
        return self.serial_port_combo.currentText().split(" ", 1)[0].strip()

    @staticmethod
    def _serial_port_label(device: str, description: str, hwid: str) -> str:
        details = " | ".join(part for part in [description, hwid] if part)
        return f"{device} — {details}" if details else device

    @staticmethod
    def _is_preferred_serial_port(description: str, hwid: str) -> bool:
        text = f"{description} {hwid}".lower()
        return any(token in text for token in ("ch347", "ch34", "wch", "usb-serial", "usb serial"))

    @Slot()
    def connect_transport(self) -> None:
        try:
            backend = self.backend_combo.currentText()
            if backend == "Mock":
                transport = MockTransport(width=self.led_count_spin.value(), height=1)
            elif backend == "Serial":
                transport = SerialTransport(self._selected_serial_port(), self.baud_spin.value())
            else:
                spi_clock_val = SPI_CLOCK_OPTIONS[self.spi_clock_combo.currentIndex()][1]
                transport = Ch347SpiTransport(
                    dll_name=self.dll_edit.text(),
                    device_index=self.device_index_spin.value(),
                    chip_select=self.chip_select_spin.value(),
                    spi_clock=spi_clock_val,
                )
            client = DebugClient(transport, require_ack=self.require_ack_check.isChecked(), log=self.log)
            client.open()
            self.transport = transport
            self.client = client
            clock_label = self.spi_clock_combo.currentText() if backend == "CH347 SPI DLL" else ""
            suffix = f" spi_clock={clock_label}" if clock_label else ""
            self.log(f"connected backend={backend}{suffix}")
        except Exception as exc:
            self.show_error(str(exc))
        self._update_buttons()

    @Slot()
    def disconnect_transport(self) -> None:
        self.stop_stream(wait=True)
        if self.client is not None:
            self.client.close()
        self.client = None
        self.transport = None
        self._update_buttons()

    @Slot()
    def handshake(self) -> None:
        try:
            self._perform_handshake()
        except Exception as exc:
            self.show_error(str(exc))

    def _perform_handshake(self) -> None:
        if self.client is None:
            return
        self.client.handshake(led_count=self.led_count_spin.value(), fps=self.fps_spin.value())
        self.client.start_stream(led_count=self.led_count_spin.value(), fps=self.fps_spin.value())
        self.client.set_brightness(self.brightness_spin.value())
        self.log("handshake/start/control snapshot completed")

    @Slot()
    def send_mode(self) -> None:
        if self.client is None:
            return
        try:
            self.client.set_mode(self._current_command())
        except Exception as exc:
            self.show_error(str(exc))

    def set_power(self, on: bool) -> None:
        if self.client is None:
            return
        try:
            self.client.set_power(on)
        except Exception as exc:
            self.show_error(str(exc))

    @Slot()
    def run_diagnostics(self) -> None:
        self.log("diagnostics started")
        self.log(f"platform={sys.platform}")
        self.log(f"backend={self.backend_combo.currentText()}")
        self._log_serial_diagnostics()
        self._log_ch347_diagnostics()
        self.log("diagnostics finished")

    def _log_serial_diagnostics(self) -> None:
        selected = self._selected_serial_port()
        self.log(f"selected serial port={selected or '(empty)'} baudrate={self.baud_spin.value()}")
        if list_ports is None:
            self.log("serial list unavailable: pyserial list_ports not loaded")
            return
        ports = list(list_ports.comports())
        if not ports:
            self.log("serial ports: none found")
            return
        self.log(f"serial ports found={len(ports)}")
        for port in ports:
            self.log(f"  {port.device}: {port.description} [{port.hwid}]")

    def _log_ch347_diagnostics(self) -> None:
        dll_name = self.dll_edit.text().strip() or str(default_dll_path())
        self.log(f"ch347 dll={dll_name}")
        dll_path = Path(dll_name)
        if dll_path.name.lower().endswith(".dll"):
            self.log(f"ch347 dll file exists={dll_path.exists()}")
        if sys.platform != "win32":
            self.log("ch347 dll check skipped: Windows-only")
            return
        try:
            dll = ctypes.WinDLL(dll_name)
        except OSError as exc:
            self.log(f"ch347 dll load failed: {exc}")
            return
        self.log("ch347 dll loaded")
        dll.CH347OpenDevice.argtypes = [ctypes.c_ulong]
        dll.CH347OpenDevice.restype = ctypes.c_void_p
        dll.CH347CloseDevice.argtypes = [ctypes.c_ulong]
        dll.CH347CloseDevice.restype = ctypes.c_bool
        index = self.device_index_spin.value()
        handle = dll.CH347OpenDevice(ctypes.c_ulong(index))
        invalid = ctypes.c_void_p(-1).value
        if handle in (None, 0, invalid):
            self.log(f"CH347OpenDevice({index}) failed: check driver, USB cable, device mode, or index")
            return
        self.log(f"CH347OpenDevice({index}) ok handle={handle}")
        closed = dll.CH347CloseDevice(ctypes.c_ulong(index))
        self.log(f"CH347CloseDevice({index}) ok={bool(closed)}")

    @Slot()
    def start_stream(self) -> None:
        if self.client is None or self.stream_thread is not None:
            return
        try:
            self._perform_handshake()
            preset = preset_by_key(str(self.preset_combo.currentData()))
            thread = QThread()
            worker = StreamWorker(
                self.client,
                preset,
                self.led_count_spin.value(),
                self.fps_spin.value(),
                self.brightness_spin.value(),
                self.speed_spin.value(),
                self.channel_spin.value(),
            )
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.log.connect(self.log)
            worker.preview.connect(self.preview.set_frame)
            worker.failed.connect(self.show_error)
            worker.stopped.connect(thread.quit)
            worker.stopped.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(self._stream_finished)
            self.stream_thread = thread
            self.stream_worker = worker
            thread.start()
            self.log("stream started")
        except Exception as exc:
            self.show_error(str(exc))
        self._update_buttons()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.stop_stream(wait=True)
        self.disconnect_transport()
        event.accept()

    @Slot()
    def stop_stream(self, wait: bool = False) -> None:
        if self.stream_worker is not None:
            self.stream_worker.stop()
            self.log("stream stop requested")
        if wait and self.stream_thread is not None:
            self.stream_thread.quit()
            self.stream_thread.wait(2000)

    @Slot()
    def _stream_finished(self) -> None:
        self.stream_thread = None
        self.stream_worker = None
        self.log("stream stopped")
        self._update_buttons()

    @Slot()
    def refresh_preview(self) -> None:
        preset = preset_by_key(str(self.preset_combo.currentData()))
        frame = render_preset(
            preset,
            led_count=self.led_count_spin.value(),
            brightness=self.brightness_spin.value(),
            speed=self.speed_spin.value(),
        )
        self.preview.set_frame(frame)

    def _current_command(self) -> dict[str, object]:
        preset = preset_by_key(str(self.preset_combo.currentData()))
        return {
            "target": "strip",
            "channel_id": self.channel_spin.value(),
            "render_target": "cloud",
            "mode": preset.key,
            "brightness": self.brightness_spin.value(),
            "speed": self.speed_spin.value(),
            "led_count": self.led_count_spin.value(),
            "colors": [{"rgb": list(color)} for color in preset.colors],
        }

    def _update_buttons(self) -> None:
        connected = self.client is not None
        streaming = self.stream_thread is not None
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.handshake_btn.setEnabled(connected and not streaming)
        self.power_on_btn.setEnabled(connected)
        self.power_off_btn.setEnabled(connected)
        self.mode_btn.setEnabled(connected)
        self.diagnostics_btn.setEnabled(not streaming)
        self.start_btn.setEnabled(connected and not streaming)
        self.stop_btn.setEnabled(streaming)

    @Slot(str)
    def log(self, message: str) -> None:
        self.log_view.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    @Slot(str)
    def show_error(self, message: str) -> None:
        self.log(f"ERROR: {message}")
        QMessageBox.warning(self, "Error", message)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
