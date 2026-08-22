from __future__ import annotations

import os
import shutil
from pathlib import Path


APP_DISPLAY_NAME = "VuxGM Media"
APP_VERSION = "1.0.0"
APP_SITE_URL = os.environ.get("VUXGM_SITE_URL", "https://vuxgm.site").rstrip("/")
APP_API_BASE = os.environ.get("VUXGM_API_BASE", f"{APP_SITE_URL}/api").rstrip("/")


def _base_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home()))


def _migrate_old_license_cache(target: Path) -> None:
    """Carry forward the clean-rebuild license cache without touching legacy app settings."""
    old = _base_appdata() / "VuxGM" / "PeiPeiRebuild"
    if not old.is_dir() or old == target:
        return
    for name in ("license.dat", "machine_id.txt", "license_public_key.txt"):
        src = old / name
        dst = target / name
        if dst.exists() or not src.exists():
            continue
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass


def app_data_dir() -> Path:
    d = _base_appdata() / "VuxGM" / "Media"
    d.mkdir(parents=True, exist_ok=True)
    _migrate_old_license_cache(d)
    return d
