from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_BUNDLED_HINTS = [Path(r"C:\Users\Admin\Desktop\Tool VietSub\ffmpeg.exe")]


def _no_window_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}
    return {}


def find_ffmpeg() -> str:
    env = os.environ.get("BILISUB_FFMPEG")
    if env and Path(env).exists():
        return env

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exedir = Path(sys.executable).resolve().parent
        meipass = Path(getattr(sys, "_MEIPASS", exedir))
        candidates += [
            exedir / "ffmpeg.exe",
            exedir / "bin" / "ffmpeg.exe",
            exedir / "_internal" / "bin" / "ffmpeg.exe",
            meipass / "bin" / "ffmpeg.exe",
        ]

    candidates += [Path(__file__).parent.parent / "bin" / "ffmpeg.exe", Path.cwd() / "ffmpeg.exe"]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    for hint in _BUNDLED_HINTS:
        if hint.exists():
            return str(hint)
    return "ffmpeg"


def find_ffprobe() -> str:
    ffmpeg = find_ffmpeg()
    p = Path(ffmpeg)
    candidate = p.with_name(p.name.replace("ffmpeg", "ffprobe"))
    if candidate.exists():
        return str(candidate)
    return shutil.which("ffprobe") or "ffprobe"


@dataclass
class VideoInfo:
    width: int
    height: int
    duration_ms: int
    rotation: int = 0
    has_audio: bool = False


def probe(video_path: str | Path) -> VideoInfo:
    ffprobe = find_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_no_window_kwargs(),
        ).stdout
        data = json.loads(out or "{}")
    except Exception:
        data = {}

    width = 0
    height = 0
    rotation = 0
    has_audio = False

    for stream in data.get("streams", []) or []:
        if stream.get("codec_type") == "audio":
            has_audio = True
        if stream.get("codec_type") != "video":
            continue

        try:
            width = int(stream.get("width") or width or 0)
            height = int(stream.get("height") or height or 0)
        except (ValueError, TypeError):
            pass

        try:
            tag_rotation = (stream.get("tags") or {}).get("rotate")
            if tag_rotation is not None:
                rotation = int(float(tag_rotation))
        except (ValueError, TypeError):
            pass

        for side_data in stream.get("side_data_list", []) or []:
            try:
                if "rotation" in side_data:
                    rotation = int(float(side_data.get("rotation") or 0))
            except (ValueError, TypeError):
                pass

    duration_ms = 0
    try:
        duration_ms = int(float((data.get("format") or {}).get("duration") or 0.0) * 1000)
    except (ValueError, TypeError):
        pass

    if duration_ms <= 0:
        for stream in data.get("streams", []) or []:
            try:
                duration_ms = max(duration_ms, int(float(stream.get("duration") or 0.0) * 1000))
            except (ValueError, TypeError):
                pass

    rotation %= 360
    if rotation in (90, 270) and width and height:
        width, height = height, width

    return VideoInfo(width=width, height=height, duration_ms=duration_ms, rotation=rotation, has_audio=has_audio)


_ERR_PAT = re.compile(
    r"(No space left|Disk (quota|full)|Permission denied|Cannot allocate|Out of memory|Invalid argument|Invalid data|Error |error while|failed|Failed|Conversion failed|Unknown encoder|Unrecognized option|not supported|No such file|moov atom|Impossible to convert|Filter .* not found|Cannot open|I/O error|corrupt)",
    re.IGNORECASE,
)

RC_CANCELLED = -9999


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                **_no_window_kwargs(),
            )
            return
        except Exception:
            pass
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run(
    cmd: list[str],
    *,
    on_progress: Optional[Callable[[int], None]] = None,
    total_ms: int = 0,
    should_stop: Optional[Callable[[], bool]] = None,
) -> tuple[int, str]:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_no_window_kwargs(),
    )
    time_re = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})")
    tail: list[str] = []
    errors: list[str] = []

    try:
        stall_s = float(os.environ.get("BILISUB_FFMPEG_STALL", "") or 600.0)
    except ValueError:
        stall_s = 600.0

    q: queue.Queue[Optional[str]] = queue.Queue()

    def _reader() -> None:
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                q.put(line)
        except Exception:
            pass
        finally:
            q.put(None)

    threading.Thread(target=_reader, daemon=True, name="ffmpeg-doc-log").start()
    last_line_ts = time.time()
    stalled = False

    try:
        while True:
            try:
                line = q.get(timeout=2.0)
            except queue.Empty:
                if should_stop is not None and should_stop():
                    _kill_tree(proc)
                    return RC_CANCELLED, "".join(tail[-10:]) + "\n(đã dừng theo yêu cầu người dùng)"
                if stall_s > 0 and time.time() - last_line_ts >= stall_s and proc.poll() is None:
                    stalled = True
                    _kill_tree(proc)
                    break
                continue

            if line is None:
                break
            last_line_ts = time.time()

            if should_stop is not None and should_stop():
                _kill_tree(proc)
                return RC_CANCELLED, "".join(tail[-10:]) + "\n(đã dừng theo yêu cầu người dùng)"

            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)

            if _ERR_PAT.search(line) and len(errors) < 12:
                s = line.strip()
                if s and s not in errors:
                    errors.append(s)

            if on_progress and total_ms > 0:
                m = time_re.search(line)
                if m:
                    h, minute, second, cs = map(int, m.groups())
                    current_ms = ((h * 60 + minute) * 60 + second) * 1000 + cs * 10
                    try:
                        on_progress(min(99, int(current_ms * 100 / total_ms)))
                    except Exception:
                        pass
    except BaseException:
        _kill_tree(proc)
        raise

    if stalled:
        try:
            proc.wait(timeout=30)
        except Exception:
            pass
    else:
        proc.wait()

    output = "".join(tail)
    if stalled:
        rc = proc.returncode if proc.returncode not in (None, 0) else 1
        output = (
            f"⏱ ffmpeg đứng im {stall_s:.0f} giây liền (nghi kẹt đọc/ghi — video hay thư mục lưu nằm trên ổ rời/ổ mạng bị ngắt?) "
            "— tool đã tự ngắt để không treo. Kiểm tra ổ đĩa rồi chạy lại.\n\n--- đuôi log ---\n"
            + output
        )
        return rc, output

    if errors:
        output = "★ DÒNG LỖI:\n" + "\n".join(errors) + "\n\n--- đuôi log ---\n" + output
    return int(proc.returncode or 0), output


def extract_frame(video_path: str | Path, time_s: float, out_png: str | Path, max_width: int = 720) -> str:
    ffmpeg = find_ffmpeg()
    t = max(0.0, float(time_s or 0.0))
    try:
        duration = probe(video_path).duration_ms / 1000.0
        if duration > 0.5 and t > duration - 0.2:
            t = min(t, duration * 0.5)
    except Exception:
        pass

    def _run(ts: float) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                ffmpeg,
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={max_width}:-1:flags=lanczos",
                str(out_png),
            ],
            capture_output=True,
            **_no_window_kwargs(),
        )

    p = _run(t)
    if not Path(out_png).exists() and t > 0:
        p = _run(0.0)
    if not Path(out_png).exists():
        err = (p.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        why = err[-1][:160] if err else ""
        raise RuntimeError(f"Không lấy được frame preview từ video. {why}")
    return str(out_png)


def target_resolution(width: int, height: int, short_side: int = 1080) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return 1920, 1080
    if width >= height:
        h = short_side
        w = round(width * h / height)
    else:
        w = short_side
        h = round(height * w / width)
    return w + (w & 1), h + (h & 1)
