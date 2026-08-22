from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Iterable

from .models import SubtitleEntry

_GHI_CHO_S = (0.4, 1.0, 2.0)


def ghi_text_ben(path: str | Path, data: str, encoding: str = "utf-8-sig") -> Path:
    """Write text atomically with small retries for Windows/AV file locks."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    last_error: Exception | None = None
    for wait_s in _GHI_CHO_S:
        try:
            tmp.write_text(data, encoding=encoding)
            os.replace(tmp, target)
            return target
        except Exception as exc:
            last_error = exc
            time.sleep(wait_s)
    try:
        tmp.unlink(missing_ok=True)
    except Exception:
        pass
    if last_error:
        raise last_error
    return target


_BLOCK_SPLIT = re.compile(r"\n\s*\n")
_TIME_LINE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")
_TAG = re.compile(r"<[^>]+>")
_ASS_TAG = re.compile(r"\{\\[^{}]*\}")
_DAU_TRUC_TIM = re.compile(r"\[\s*PeiPei[^\]]*?\bk\s*=\s*([0-9]+(?:[.,][0-9]+)?)\s*\]", re.IGNORECASE)
_DAU_TRUC_RE = re.compile(r"^\[\s*PeiPei[^\]]*\]$", re.IGNORECASE)


def dau_truc_cue(k: float) -> str:
    return f"[PeiPei k={float(k):.4g}]"


def doc_dau_truc(path: str | Path) -> float:
    try:
        text = _read_text(path)
        m = _DAU_TRUC_TIM.search(text)
        if m:
            return float(m.group(1).replace(",", "."))
    except Exception:
        pass
    return 1.0


def ghi_dau_truc(path: str | Path, k: float) -> None:
    try:
        text = _read_text(path)
    except Exception:
        text = ""
    blocks = [b.strip() for b in _BLOCK_SPLIT.split(text) if b.strip()]
    blocks = [b for b in blocks if not _DAU_TRUC_RE.search(b)]
    blocks.insert(0, f"1\n00:00:00,000 --> 00:00:00,000\n{dau_truc_cue(k)}")
    ghi_text_ben(path, "\n\n".join(blocks) + "\n", encoding="utf-8-sig")


def _read_text(path: str | Path) -> str:
    p = Path(path)
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1258", "latin-1"):
        try:
            return p.read_text(encoding=enc)
        except UnicodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def parse_srt(path: str | Path) -> list[SubtitleEntry]:
    text = _read_text(path).replace("\r\n", "\n").replace("\r", "\n")
    entries: list[SubtitleEntry] = []
    idx = 0
    for block in _BLOCK_SPLIT.split(text.strip()):
        block = block.strip()
        if not block:
            continue
        m = _TIME_LINE.search(block)
        if not m:
            continue
        start = SubtitleEntry.parse_time(m.group(1))
        end = SubtitleEntry.parse_time(m.group(2))
        lines = block.split("\n")
        time_index = next((i for i, line in enumerate(lines) if _TIME_LINE.search(line)), 0)
        content = " ".join(line.strip() for line in lines[time_index + 1 :] if line.strip())
        content = _TAG.sub("", content)
        content = _ASS_TAG.sub("", content)
        content = content.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ")
        content = " ".join(content.split()).strip()
        if not content:
            continue
        if _DAU_TRUC_RE.match(content) or (start == 0 and end == 0 and "peipei" in content.lower()):
            continue
        idx += 1
        entries.append(SubtitleEntry(index=idx, start_ms=start, end_ms=end, text=content))
    return entries


def export_srt(entries: Iterable[SubtitleEntry], path: str | Path, use_translated: bool = True) -> Path:
    out: list[str] = []
    for i, entry in enumerate(entries, 1):
        body = entry.output_text if use_translated else entry.text
        out.append(
            f"{i}\n{SubtitleEntry.format_time(entry.start_ms)} --> {SubtitleEntry.format_time(entry.end_ms)}\n{body}\n"
        )
    return ghi_text_ben(path, "\n".join(out), encoding="utf-8-sig")


def _simple_norm(text: str) -> str:
    text = re.sub(r"(?<=\d)[\W_]+(?=\d)", "#", text or "", flags=re.UNICODE)
    text = re.sub(r"[^\w#]+|_+", "", text, flags=re.UNICODE)
    return text.lower()


def merge_duplicate_entries(entries: list[SubtitleEntry], max_gap_ms: int = 1500) -> list[SubtitleEntry]:
    out: list[SubtitleEntry] = []
    kept_diff_source = 0
    example = ""
    for entry in entries:
        last = out[-1] if out else None
        if (
            last is not None
            and not entry.is_art
            and not last.is_art
            and entry.pos == last.pos
            and _simple_norm(entry.translated or entry.text)
            and _simple_norm(entry.translated or entry.text) == _simple_norm(last.translated or last.text)
            and entry.start_ms - last.end_ms <= max_gap_ms
        ):
            # Same displayed cue. Merge only when the source text is also plausibly
            # the same; otherwise keep it but suppress duplicated TTS.
            a = "".join((last.text or "").split()).lower()
            b = "".join((entry.text or "").split()).lower()
            same_source = not a or not b or a in b or b in a
            if same_source:
                last.end_ms = max(last.end_ms, entry.end_ms)
                continue
            kept_diff_source += 1
            entry.meta["speak"] = False
            if not example:
                example = (entry.translated or entry.text or "")[:40]
        out.append(entry)

    for i, entry in enumerate(out, 1):
        entry.index = i
    merge_duplicate_entries.last_kept_diff_src = (kept_diff_source, example)
    return out


merge_duplicate_entries.last_kept_diff_src = (0, "")


def merge_short_entries(entries: list[SubtitleEntry], min_duration_ms: int = 400) -> list[SubtitleEntry]:
    if not entries:
        return []

    result: list[SubtitleEntry] = []
    buffer = entries[0].copy()
    for nxt in entries[1:]:
        gap = nxt.start_ms - buffer.end_ms
        mergeable = (
            buffer.duration_ms < min_duration_ms
            and gap >= 0
            and gap <= 120
            and buffer.pos == nxt.pos
            and not buffer.is_art
            and not nxt.is_art
        )
        if mergeable:
            buffer.end_ms = max(buffer.end_ms, nxt.end_ms)
            if nxt.text.strip():
                buffer.text = (buffer.text.strip() + " " + nxt.text.strip()).strip()
            if nxt.translated.strip():
                buffer.translated = (buffer.translated.strip() + " " + nxt.translated.strip()).strip()
        else:
            result.append(buffer)
            buffer = nxt.copy()
    result.append(buffer)
    for i, entry in enumerate(result, 1):
        entry.index = i
    return result


ASS_PRESETS: dict[str, dict] = {
    "Neon": {"text_color": "#FFFFFF", "outline_color": "#00E5FF", "outline_width": 3.5, "shadow": 1.0, "bold": True},
    "Classic": {"text_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 3.0, "shadow": 1.2, "bold": True},
    "Minimal": {"text_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 1.6, "shadow": 0.4, "bold": False},
    "Bold": {"text_color": "#FFE000", "outline_color": "#000000", "outline_width": 4.2, "shadow": 1.4, "bold": True},
    "Mint": {"text_color": "#FFFFFF", "outline_color": "#22C55E", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Rose": {"text_color": "#FFFFFF", "outline_color": "#FF4D8D", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Sky": {"text_color": "#FFFFFF", "outline_color": "#38BDF8", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Sunset": {"text_color": "#FFB347", "outline_color": "#7A2E00", "outline_width": 3.4, "shadow": 1.2, "bold": True},
    "Lavender": {"text_color": "#FFFFFF", "outline_color": "#A78BFA", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Lemon": {"text_color": "#FFF16A", "outline_color": "#3A3A00", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Coral": {"text_color": "#FFFFFF", "outline_color": "#FF6B5B", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Teal": {"text_color": "#FFFFFF", "outline_color": "#14B8A6", "outline_width": 3.2, "shadow": 1.0, "bold": True},
    "Không viền": {"text_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 0.0, "shadow": 0.0, "bold": True},
    "Chữ đen": {"text_color": "#111111", "outline_color": "#FFFFFF", "outline_width": 2.4, "shadow": 0.6, "bold": True},
    "Hộp trắng": {"text_color": "#111111", "outline_color": "#000000", "outline_width": 8.0, "shadow": 0.0, "bold": True, "box": True, "box_color": "#FFFFFF"},
    "Hộp đen": {"text_color": "#FFFFFF", "outline_color": "#000000", "outline_width": 8.0, "shadow": 0.0, "bold": True, "box": True, "box_color": "#000000"},
    "Hộp vàng": {"text_color": "#111111", "outline_color": "#000000", "outline_width": 8.0, "shadow": 0.0, "bold": True, "box": True, "box_color": "#FFD400"},
}
PRESET_NAMES = list(ASS_PRESETS.keys())
PRESET_BOX_NAMES = [name for name, cfg in ASS_PRESETS.items() if cfg.get("box")]


def get_preset(name: str) -> dict:
    return ASS_PRESETS.get(name, {})


def _hex_to_ass(value: str, alpha: int = 0) -> str:
    value = (value or "#FFFFFF").lstrip("#")
    if len(value) != 6:
        value = "FFFFFF"
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&"


_FONT_THEO_TIENG = {
    "zh": "Microsoft YaHei",
    "ja": "Yu Gothic",
    "ko": "Malgun Gothic",
    "th": "Leelawadee UI",
    "ar": "Segoe UI",
    "hi": "Nirmala UI",
}


def font_for_language(lang: str, font_hien_tai: str = "") -> str:
    mapped = _FONT_THEO_TIENG.get(str(lang or "").strip().lower())
    return mapped or (font_hien_tai or "Arial")


def _ass_time(ms: int) -> str:
    ms = max(0, int(ms))
    total_s, rem_ms = divmod(ms, 1000)
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    cs = rem_ms // 10
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def export_ass(
    entries: Iterable[SubtitleEntry],
    path: str | Path,
    *,
    video_width: int = 1920,
    video_height: int = 1080,
    preset: str = "Classic",
    font: str = "Arial",
    font_size: int = 54,
    language: str = "vi",
) -> Path:
    """Basic ASS export compatible with the reconstructed render path.

    The original module contains a much larger art-text/layout engine. This keeps
    standard subtitle rendering functional while that advanced section is rebuilt.
    """
    cfg = {**ASS_PRESETS["Classic"], **get_preset(preset)}
    font = font_for_language(language, font)
    primary = _hex_to_ass(cfg.get("text_color", "#FFFFFF"))
    outline = _hex_to_ass(cfg.get("outline_color", "#000000"))
    bold = -1 if cfg.get("bold", False) else 0
    outline_w = float(cfg.get("outline_width", 3.0))
    shadow = float(cfg.get("shadow", 1.0))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {max(1, int(video_width))}
PlayResY: {max(1, int(video_height))}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{int(font_size)},{primary},{primary},{outline},&H64000000&,{bold},0,0,0,100,100,0,0,1,{outline_w:.1f},{shadow:.1f},2,40,40,48,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    lines = [header]
    for entry in entries:
        text = (entry.output_text or "").replace("\n", r"\N").replace("{", r"\{").replace("}", r"\}")
        lines.append(f"Dialogue: 0,{_ass_time(entry.start_ms)},{_ass_time(entry.end_ms)},Default,,0,0,0,,{text}\n")
    return ghi_text_ben(path, "".join(lines), encoding="utf-8-sig")
