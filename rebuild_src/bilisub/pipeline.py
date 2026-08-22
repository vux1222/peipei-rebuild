from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from . import srt as srt_mod
from .asr import WhisperASR
from .config import APP_VERSION, Settings
from .ffmpeg_utils import _no_window_kwargs, find_ffmpeg, probe, run as run_ffmpeg
from .models import SubtitleEntry

Log = Callable[[str], None]
Progress = Callable[[str, int], None]


@dataclass
class PipelineInput:
    video_path: Optional[str] = None
    srt_path: Optional[str] = None
    output_path: Optional[str] = None
    source: str = "auto"
    voice: Optional[str] = None
    do_subtitle: bool = True
    do_translate: bool = True
    do_review: bool = False
    do_tts: bool = True
    do_render: bool = True
    merge_short: bool = True
    preview_seconds: int = 0
    export_srt_only: bool = False


@dataclass
class PipelineResult:
    entries: list[SubtitleEntry]
    srt_out: Optional[str] = None
    ass_out: Optional[str] = None
    audio_out: Optional[str] = None
    video_out: Optional[str] = None
    detected_language: Optional[str] = None


def _emit_log(log: Optional[Log], message: str) -> None:
    if log:
        log(message)


def _emit_progress(progress: Optional[Progress], stage: str, percent: int) -> None:
    if progress:
        progress(stage, max(0, min(100, int(percent))))


def _check_stop(should_stop: Optional[Callable[[], bool]]) -> None:
    if should_stop and should_stop():
        raise RuntimeError("Đã dừng theo yêu cầu người dùng")


def _trim_for_preview(src: str, work: Path, seconds: int, log: Optional[Log] = None) -> str:
    if seconds <= 0:
        return src
    dst = str(work / "preview_input.mp4")
    ffmpeg = find_ffmpeg()
    base = ["-hide_banner", "-loglevel", "error", "-ss", "0", "-i", src, "-t", str(seconds)]
    subprocess.run([ffmpeg, *base, "-c", "copy", "-y", dst], capture_output=True, **_no_window_kwargs())
    if Path(dst).exists() and Path(dst).stat().st_size > 0:
        _emit_log(log, f"Preview {seconds}s: {dst}")
        return dst
    subprocess.run(
        [ffmpeg, *base, "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-y", dst],
        capture_output=True,
        **_no_window_kwargs(),
    )
    return dst if Path(dst).exists() else src


def _default_output_path(video_path: str) -> str:
    p = Path(video_path)
    return str(p.with_name(f"{p.stem}_peipei_rebuild.mp4"))


def _escape_filter_path(path: str | Path) -> str:
    value = str(Path(path).resolve()).replace("\\", "/")
    value = value.replace(":", r"\:").replace("'", r"\'")
    return value


def _render_basic(
    video_path: str,
    output_path: str,
    ass_path: Optional[str],
    *,
    total_ms: int,
    log: Optional[Log],
    progress: Optional[Progress],
    should_stop: Optional[Callable[[], bool]],
) -> str:
    ffmpeg = find_ffmpeg()
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if ass_path:
        escaped = _escape_filter_path(ass_path)
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"ass=filename='{escaped}'",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(out),
        ]
    else:
        cmd = [ffmpeg, "-hide_banner", "-y", "-i", video_path, "-map", "0", "-c", "copy", str(out)]

    _emit_log(log, "Đang render bằng FFmpeg…")

    def ff_progress(pct: int) -> None:
        _emit_progress(progress, "Xuất bản", pct)

    rc, tail = run_ffmpeg(cmd, on_progress=ff_progress, total_ms=total_ms, should_stop=should_stop)
    if rc != 0:
        raise RuntimeError(f"FFmpeg thất bại (rc={rc}).\n{tail[-3000:]}")
    if not out.exists() or out.stat().st_size <= 0:
        raise RuntimeError("FFmpeg kết thúc nhưng không tạo được video đầu ra.")
    return str(out)


def run_pipeline(
    settings: Settings,
    inp: PipelineInput,
    *,
    log: Optional[Log] = None,
    progress: Optional[Progress] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> PipelineResult:
    """Run the reconstructed baseline pipeline.

    Working now: existing SRT import or faster-whisper ASR, subtitle cleanup,
    optional short-cue merge, SRT/ASS export, preview trimming, and basic FFmpeg
    render. AI translation and TTS remain explicit pending stages.
    """
    _emit_log(log, f"PeiPei rebuild pipeline {APP_VERSION}")
    _emit_progress(progress, "Chuẩn bị", 0)
    _check_stop(should_stop)

    video_path = str(inp.video_path or "").strip()
    srt_path = str(inp.srt_path or "").strip()

    if video_path and not Path(video_path).exists():
        raise FileNotFoundError(f"Không tìm thấy video: {video_path}")
    if srt_path and not Path(srt_path).exists():
        raise FileNotFoundError(f"Không tìm thấy SRT: {srt_path}")

    if inp.do_translate:
        raise NotImplementedError("Khâu dịch AI đang được phục dựng; hãy tắt 'Dịch' ở bản rebuild hiện tại.")
    if inp.do_tts:
        raise NotImplementedError("Khâu TTS đang được phục dựng; hãy tắt 'Tạo giọng' ở bản rebuild hiện tại.")

    work_root = Path(tempfile.mkdtemp(prefix="peipei_rebuild_"))
    try:
        working_video = video_path
        if video_path and inp.preview_seconds > 0:
            working_video = _trim_for_preview(video_path, work_root, inp.preview_seconds, log)

        entries: list[SubtitleEntry] = []
        detected_language: Optional[str] = None

        if srt_path:
            _emit_progress(progress, "Đọc phụ đề", 10)
            entries = srt_mod.parse_srt(srt_path)
            _emit_log(log, f"Đã đọc {len(entries)} câu phụ đề từ {Path(srt_path).name}.")
        elif inp.do_subtitle:
            if not working_video:
                raise ValueError("Cần video hoặc SRT để tạo phụ đề.")
            _emit_progress(progress, "Tách transcript", 5)
            asr = WhisperASR(settings.asr_model, settings.asr_device, settings.asr_compute_type, log=log)

            def asr_progress(pct: int) -> None:
                _check_stop(should_stop)
                _emit_progress(progress, "Tách transcript", 5 + round(pct * 0.25))

            entries = asr.transcribe(
                working_video,
                language=settings.source_language,
                progress=asr_progress,
            )
            detected_language = asr.detected_language
            _emit_log(log, f"ASR: {len(entries)} câu.")

        if inp.merge_short and entries:
            before = len(entries)
            entries = srt_mod.merge_short_entries(entries)
            _emit_log(log, f"Gộp câu ngắn: {before} → {len(entries)} câu.")

        _check_stop(should_stop)

        stem_source = Path(video_path or srt_path or "output")
        base_dir = Path(inp.output_path).parent if inp.output_path else stem_source.parent
        base_stem = Path(inp.output_path).stem if inp.output_path else f"{stem_source.stem}_peipei_rebuild"
        base_dir.mkdir(parents=True, exist_ok=True)

        result = PipelineResult(entries=entries, detected_language=detected_language)

        if entries:
            _emit_progress(progress, "Tạo phụ đề", 35)
            srt_out = base_dir / f"{base_stem}.srt"
            srt_mod.export_srt(entries, srt_out, use_translated=False)
            result.srt_out = str(srt_out)
            _emit_log(log, f"SRT: {srt_out}")

            if inp.do_subtitle:
                width, height = 1920, 1080
                if working_video:
                    info = probe(working_video)
                    width = info.width or width
                    height = info.height or height
                ass_out = base_dir / f"{base_stem}.ass"
                srt_mod.export_ass(
                    entries,
                    ass_out,
                    video_width=width,
                    video_height=height,
                    preset=settings.subtitle_preset,
                    font=settings.ass_font,
                    font_size=settings.ass_font_size,
                    language=settings.subtitle_language,
                )
                result.ass_out = str(ass_out)
                _emit_log(log, f"ASS: {ass_out}")

        if inp.export_srt_only or not inp.do_render:
            _emit_progress(progress, "Hoàn tất", 100)
            return result

        if not working_video:
            raise ValueError("Cần video để thực hiện bước render.")

        _check_stop(should_stop)
        output_path = str(inp.output_path or _default_output_path(video_path))
        info = probe(working_video)
        result.video_out = _render_basic(
            working_video,
            output_path,
            result.ass_out if inp.do_subtitle else None,
            total_ms=info.duration_ms,
            log=log,
            progress=progress,
            should_stop=should_stop,
        )
        _emit_progress(progress, "Hoàn tất", 100)
        _emit_log(log, f"Hoàn tất: {result.video_out}")
        return result
    finally:
        try:
            shutil.rmtree(work_root, ignore_errors=True)
        except Exception:
            pass
