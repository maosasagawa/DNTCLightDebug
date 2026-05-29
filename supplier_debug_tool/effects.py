from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence


Color = tuple[int, int, int]
Frame = list[Color]


@dataclass(frozen=True)
class EffectPreset:
    key: str
    name: str
    colors: tuple[Color, ...]
    brightness: float
    speed: float


PRESETS: tuple[EffectPreset, ...] = (
    EffectPreset("warm_static", "暖色常亮", ((255, 120, 40),), 0.8, 1.0),
    EffectPreset("cool_static", "冷色常亮", ((40, 120, 255),), 0.8, 1.0),
    EffectPreset("breath", "呼吸", ((255, 80, 40), (80, 20, 180)), 0.9, 2.0),
    EffectPreset("flow", "流水渐变", ((255, 0, 80), (40, 120, 255), (0, 220, 180)), 0.9, 2.0),
    EffectPreset("rainbow", "彩虹", ((255, 0, 0), (255, 180, 0), (0, 220, 80), (0, 120, 255), (160, 60, 255)), 0.9, 3.0),
)


def preset_by_key(key: str) -> EffectPreset:
    for preset in PRESETS:
        if preset.key == key:
            return preset
    return PRESETS[0]


def render_preset(
    preset: EffectPreset,
    *,
    led_count: int,
    now_s: float | None = None,
    brightness: float | None = None,
    speed: float | None = None,
) -> Frame:
    if now_s is None:
        now_s = time.time()
    effective_brightness = _clamp_float(preset.brightness if brightness is None else brightness)
    effective_speed = max(0.1, float(preset.speed if speed is None else speed))
    led_count = max(1, int(led_count))

    if preset.key.endswith("static"):
        return [_apply_brightness(_gradient(preset.colors, i / max(1, led_count - 1)), effective_brightness) for i in range(led_count)]

    if preset.key == "breath":
        period = max(0.5, effective_speed * 2.0)
        t = (now_s % period) / period
        factor = 0.08 + 0.92 * (math.sin(t * math.pi) ** 2.2)
        return [_apply_brightness(_gradient(preset.colors, i / max(1, led_count - 1)), effective_brightness * factor) for i in range(led_count)]

    if preset.key in {"flow", "rainbow"}:
        period = max(0.5, effective_speed)
        phase = (now_s % period) / period
        return [
            _apply_brightness(_gradient(preset.colors, (i / max(1, led_count - 1) - phase) % 1.0, loop=True), effective_brightness)
            for i in range(led_count)
        ]

    return [_apply_brightness(preset.colors[0], effective_brightness) for _ in range(led_count)]


def _gradient(colors: Sequence[Color], pos: float, *, loop: bool = False) -> Color:
    if not colors:
        return (0, 0, 0)
    if len(colors) == 1:
        return colors[0]
    if loop:
        pos = pos % 1.0
        scaled = pos * len(colors)
        idx = int(math.floor(scaled)) % len(colors)
        next_idx = (idx + 1) % len(colors)
        t = scaled - math.floor(scaled)
        return _lerp_color(colors[idx], colors[next_idx], t)
    pos = _clamp_float(pos)
    scaled = pos * (len(colors) - 1)
    idx = int(math.floor(scaled))
    if idx >= len(colors) - 1:
        return colors[-1]
    return _lerp_color(colors[idx], colors[idx + 1], scaled - idx)


def _lerp_color(a: Color, b: Color, t: float) -> Color:
    t = _smoothstep(t)
    return (_clamp_int(a[0] + (b[0] - a[0]) * t), _clamp_int(a[1] + (b[1] - a[1]) * t), _clamp_int(a[2] + (b[2] - a[2]) * t))


def _apply_brightness(color: Color, brightness: float) -> Color:
    b = _clamp_float(brightness)
    return (_clamp_int(color[0] * b), _clamp_int(color[1] * b), _clamp_int(color[2] * b))


def _smoothstep(t: float) -> float:
    t = _clamp_float(t)
    return t * t * (3.0 - 2.0 * t)


def _clamp_float(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _clamp_int(value: float) -> int:
    return max(0, min(255, int(round(value))))
