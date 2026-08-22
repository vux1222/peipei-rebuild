from __future__ import annotations

import importlib
import os
import platform
import shutil
import struct
import sys
from pathlib import Path


MODULES = [
    "PyQt6",
    "numpy",
    "cv2",
    "av",
    "onnxruntime",
    "ctranslate2",
    "faster_whisper",
    "rapidocr_onnxruntime",
    "edge_tts",
    "cryptography",
    "PIL",
    "pypinyin",
    "yt_dlp",
]

OPTIONAL_MODULES = ["vieneu", "sea_g2p"]

REQUIRED_FILES = [
    Path("_internal/bin/ffmpeg.exe"),
    Path("_internal/bin/ffprobe.exe"),
]

OPTIONAL_FILES = [
    Path("_internal/faster_whisper/assets/silero_vad_v6.onnx"),
    Path("_internal/sea_g2p/sea_g2p.bin"),
]


def result(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK" if ok else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")


def check_python() -> bool:
    is_313 = sys.version_info[:2] == (3, 13)
    is_64 = struct.calcsize("P") * 8 == 64
    result(is_313, "Python 3.13", platform.python_version())
    result(is_64, "64-bit Python", f"{struct.calcsize('P') * 8}-bit")
    return is_313 and is_64


def check_modules() -> bool:
    ok_all = True
    for name in MODULES:
        try:
            mod = importlib.import_module(name)
            version = getattr(mod, "__version__", "")
            result(True, f"import {name}", str(version))
        except Exception as exc:
            ok_all = False
            result(False, f"import {name}", repr(exc))

    for name in OPTIONAL_MODULES:
        try:
            mod = importlib.import_module(name)
            version = getattr(mod, "__version__", "")
            result(True, f"optional import {name}", str(version))
        except Exception as exc:
            result(False, f"optional import {name}", repr(exc))

    return ok_all


def check_runtime_tree(app_root: Path) -> bool:
    ok_all = True
    for rel in REQUIRED_FILES:
        path = app_root / rel
        ok = path.exists()
        ok_all &= ok
        result(ok, str(rel), str(path))

    for rel in OPTIONAL_FILES:
        path = app_root / rel
        result(path.exists(), f"optional {rel}", str(path))

    return ok_all


def check_path_tools() -> None:
    for name in ("ffmpeg", "ffprobe"):
        found = shutil.which(name)
        result(bool(found), f"PATH {name}", found or "not found")


def main() -> int:
    print("PeiPei rebuild runtime check")
    print(f"Python executable: {sys.executable}")
    print(f"Working directory: {Path.cwd()}")

    app_root = Path(os.environ.get("PEIPEI_APP_ROOT", Path.cwd())).resolve()
    print(f"App root: {app_root}")

    ok = check_python()
    ok = check_modules() and ok
    ok = check_runtime_tree(app_root) and ok
    check_path_tools()

    print()
    if ok:
        print("Core runtime checks passed.")
        return 0

    print("One or more core runtime checks failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
