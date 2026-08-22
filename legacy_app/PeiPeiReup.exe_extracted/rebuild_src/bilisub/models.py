from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Optional

_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


@dataclass
class SubtitleEntry:
    """One subtitle cue shared by ASR, translation, TTS and rendering."""

    index: int = 0
    start_ms: int = 0
    end_ms: int = 0
    text: str = ""
    translated: str = ""
    voice_text: str = ""
    pos: Optional[tuple[float, float]] = None
    font_scale: float = 1.0
    bold: bool = False
    vertical: bool = False
    is_art: bool = False
    bbox: Optional[tuple[float, float, float, float]] = None
    voice_override: Optional[str] = None
    speaker: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @staticmethod
    def parse_time(value: str) -> int:
        m = _TIME_RE.search(value.strip())
        if not m:
            raise ValueError(f"Định dạng thời gian không hợp lệ: {value!r}")
        h, minute, second, frac = m.groups()
        ms = int(frac.ljust(3, "0")[:3])
        return ((int(h) * 60 + int(minute)) * 60 + int(second)) * 1000 + ms

    @staticmethod
    def format_time(value: int) -> str:
        value = max(0, int(value))
        second_total, ms = divmod(value, 1000)
        minute_total, second = divmod(second_total, 60)
        hour, minute = divmod(minute_total, 60)
        return f"{hour:02d}:{minute:02d}:{second:02d},{ms:03d}"

    @property
    def output_text(self) -> str:
        return (self.translated or self.text or "").strip()

    @property
    def speak_text(self) -> str:
        return (self.voice_text or self.translated or self.text or "").strip()

    def copy(self, **changes: Any) -> "SubtitleEntry":
        return replace(self, **changes)


@dataclass(frozen=True)
class TranslationPlan:
    provider: str = ""
    total_entries: int = 0
    total_chars: int = 0
    call_count: int = 0
    max_items_per_call: int = 0
    label: str = ""


@dataclass
class RenderConfig:
    """Common render options used by the reconstructed pipeline.

    The original object has more fields; ``extra`` keeps the interface extensible
    while the remaining render module is reconstructed.
    """

    input_video: str = ""
    output_path: str = ""
    subtitle_path: str = ""
    audio_path: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    original_volume: float = 1.0
    video_speed: float = 1.0
    subtitle_enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)
