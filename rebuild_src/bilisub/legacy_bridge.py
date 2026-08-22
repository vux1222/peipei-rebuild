from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class LegacyPaths:
    repo_root: Path
    extracted_root: Path
    pyz_root: Path
    bilisub_root: Path
    gui_root: Path
    internal_root: Path


def _repo_root() -> Path:
    # rebuild_src/bilisub/legacy_bridge.py -> repository root
    return Path(__file__).resolve().parents[2]


def find_legacy_paths() -> LegacyPaths:
    repo = _repo_root()
    extracted = repo / "legacy_app" / "PeiPeiReup.exe_extracted"
    candidates = sorted(extracted.glob("PYZ.pyz_*_extracted")) if extracted.is_dir() else []
    pyz = next(
        (
            p
            for p in candidates
            if (p / "bilisub" / "config.pyc").exists()
            and (p / "bilisub" / "gui" / "main_window.pyc").exists()
        ),
        None,
    )
    if pyz is None:
        override = os.environ.get("VUXGM_LEGACY_PYZ", "").strip()
        if override:
            p = Path(override).expanduser().resolve()
            if (p / "bilisub" / "config.pyc").exists() and (p / "bilisub" / "gui" / "main_window.pyc").exists():
                pyz = p
                extracted = p.parent
    if pyz is None:
        raise FileNotFoundError(
            "Không tìm thấy PYZ legacy chứa bilisub/config.pyc và bilisub/gui/main_window.pyc. "
            "Giữ thư mục legacy_app trong repo hoặc đặt VUXGM_LEGACY_PYZ."
        )

    internal = repo / "legacy_app" / "_internal"
    if not internal.exists():
        alt = extracted / "_internal"
        if alt.exists():
            internal = alt

    return LegacyPaths(
        repo_root=repo,
        extracted_root=extracted,
        pyz_root=pyz,
        bilisub_root=pyz / "bilisub",
        gui_root=pyz / "bilisub" / "gui",
        internal_root=internal,
    )


def _prepend_env_path(path: Path) -> None:
    if not path.is_dir():
        return
    value = str(path)
    current = os.environ.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if value.lower() not in {p.lower() for p in parts}:
        os.environ["PATH"] = value + (os.pathsep + current if current else "")


def _prepare_native_runtime(paths: LegacyPaths) -> None:
    internal = paths.internal_root
    if not internal.is_dir():
        return

    value = str(internal)
    if value not in sys.path:
        sys.path.insert(0, value)

    dll_dirs = [
        internal,
        internal / "bin",
        internal / "PyQt6" / "Qt6" / "bin",
        internal / "onnxruntime" / "capi",
    ]
    for d in dll_dirs:
        _prepend_env_path(d)
        if sys.platform == "win32" and d.is_dir() and hasattr(os, "add_dll_directory"):
            try:
                handle = os.add_dll_directory(str(d))
                _DLL_HANDLES.append(handle)
            except OSError:
                pass


_DLL_HANDLES: list[object] = []


def _load_pyc(module_name: str, path: Path) -> ModuleType:
    loader = importlib.machinery.SourcelessFileLoader(module_name, str(path))
    spec = importlib.util.spec_from_loader(module_name, loader)
    if spec is None:
        raise ImportError(f"Không tạo được module spec cho {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    loader.exec_module(module)
    return module


def _replace_package_path(package: ModuleType, first: Path, second: Path) -> None:
    ordered: list[str] = []
    for p in (first, second):
        s = str(p)
        if s not in ordered:
            ordered.append(s)
    package.__path__ = ordered  # type: ignore[attr-defined]


def prepare_legacy_runtime() -> tuple[LegacyPaths, ModuleType]:
    """Load original bytecode while replacing owned service integrations.

    Legacy modules provide the old UI/feature behavior.  VuxGM source modules are
    preloaded for license, credit and renewal before legacy paths become first in
    module resolution, so the retired services are never imported.
    """
    paths = find_legacy_paths()
    _prepare_native_runtime(paths)

    import bilisub

    source_bilisub = Path(__file__).resolve().parent
    source_gui = source_bilisub / "gui"

    from . import config as source_config

    source_config.APP_VERSION = "1.0.0"
    from . import license_client as source_license_client  # noqa: F401
    from . import license_bootstrap as source_license_bootstrap  # noqa: F401
    from . import vuxgm_license as license_facade
    from . import credit as credit_adapter
    from . import giahan as renewal_adapter
    from . import gui as gui_pkg
    from .gui import license_dialog as source_license_dialog

    _replace_package_path(bilisub, paths.bilisub_root, source_bilisub)
    _replace_package_path(gui_pkg, source_gui, paths.gui_root)

    legacy_config = _load_pyc("bilisub.config", paths.bilisub_root / "config.pyc")
    legacy_config.APP_VERSION = "1.0.0"
    legacy_config.LICENSE_ENABLED = True

    sys.modules["bilisub.license_client"] = license_facade
    sys.modules["bilisub.credit"] = credit_adapter
    sys.modules["bilisub.giahan"] = renewal_adapter
    sys.modules["bilisub.gui.license_dialog"] = source_license_dialog
    setattr(bilisub, "config", legacy_config)
    setattr(bilisub, "license_client", license_facade)
    setattr(bilisub, "credit", credit_adapter)
    setattr(bilisub, "giahan", renewal_adapter)
    setattr(gui_pkg, "license_dialog", source_license_dialog)

    legacy_main = _load_pyc(
        "bilisub.gui._legacy_main_window",
        paths.gui_root / "main_window.pyc",
    )
    legacy_main.APP_VERSION = "1.0.0"

    original_asset_path = legacy_main.asset_path
    vux_icon = paths.repo_root / "rebuild_src" / "assets" / "vuxgm_icon.svg"

    def asset_path(*names: str) -> str:
        lowered = {str(x).lower() for x in names}
        if vux_icon.exists() and lowered.intersection({"icon.ico", "logo.png", "peipei.png"}):
            return str(vux_icon)
        return original_asset_path(*names)

    legacy_main.asset_path = asset_path
    return paths, legacy_main
