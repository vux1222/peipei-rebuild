from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import APP_API_BASE, app_data_dir
from .license_client import API_TIMEOUT_SECONDS, LicenseError


PUBLIC_KEY_CACHE_NAME = "license_public_key.txt"


def _validate_public_key(value: str) -> str:
    text = (value or "").strip()
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception as exc:
        raise LicenseError("Public key Ed25519 từ server không phải Base64 hợp lệ.") from exc
    if len(raw) != 32:
        raise LicenseError("Public key Ed25519 từ server không đúng 32 byte.")
    return text


def _error_message(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        return str(data.get("statusMessage") or data.get("message") or fallback)
    return fallback


def fetch_public_key(api_base: str = APP_API_BASE) -> str:
    """Fetch the VuxGM Ed25519 public key over normal certificate-verified HTTPS."""
    url = f"{api_base.rstrip('/')}/license/public-key"
    req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS, context=ssl.create_default_context()) as res:
            raw = res.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        message = f"Không lấy được VuxGM public key (HTTP {exc.code})."
        try:
            data = json.loads(exc.read().decode("utf-8", errors="replace"))
            message = _error_message(data, message)
        except Exception:
            pass
        raise LicenseError(message, status_code=exc.code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LicenseError("Không kết nối được vuxgm.site để lấy public key license.", network=True) from exc
    except json.JSONDecodeError as exc:
        raise LicenseError("API public-key của VuxGM trả JSON không hợp lệ.") from exc

    if not isinstance(data, dict):
        raise LicenseError("API public-key của VuxGM trả dữ liệu không hợp lệ.")
    if str(data.get("algorithm") or "").strip().lower() != "ed25519":
        raise LicenseError("Server VuxGM không trả public key Ed25519.")
    return _validate_public_key(str(data.get("public_key") or ""))


def get_license_public_key() -> str:
    """Return a pinned public key for the clean VuxGM app.

    Priority:
      1. Explicit VUXGM_LICENSE_PUBLIC_KEY environment override.
      2. Public key pinned locally after a previous successful HTTPS fetch.
      3. First-run fetch from https://vuxgm.site/api/license/public-key, then pin it.

    The public key is not secret. Pinning it locally lets cached licenses continue to
    verify while offline and avoids replacing the trust key on every app launch.
    """
    override = os.environ.get("VUXGM_LICENSE_PUBLIC_KEY", "").strip()
    if override:
        return _validate_public_key(override)

    cache_path: Path = app_data_dir() / PUBLIC_KEY_CACHE_NAME
    try:
        if cache_path.exists():
            return _validate_public_key(cache_path.read_text(encoding="utf-8"))
    except LicenseError:
        try:
            cache_path.unlink(missing_ok=True)
        except Exception:
            pass
    except Exception:
        pass

    key = fetch_public_key()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(key, encoding="utf-8")
    except Exception:
        # The app can still run this session even if the public-key cache cannot be written.
        pass
    return key
