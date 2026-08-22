from __future__ import annotations

"""Compatibility surface for the old application's credit hooks.

The PeiPei credit service is intentionally not used.  Until VuxGM's own credit
API is finalized, all translation providers operate in normal BYOK/local mode.
Keeping the old function names lets restored bytecode modules run without ever
contacting the old credit domain.
"""

import os
from typing import Optional


BAL_OK = "ok"
BAL_NO_LICENSE = "no_license"
BAL_EXPIRED = "expired"
BAL_REVOKED = "revoked"
BAL_UNREGISTERED = "unregistered"
BAL_OFFLINE = "offline"

_GOOGLE_NATIVE = os.environ.get(
    "BILISUB_GEMINI_BASE", "https://generativelanguage.googleapis.com/v1beta"
).rstrip("/")


def link_diag() -> str:
    return "VuxGM credit API chưa được cấu hình; đang dùng BYOK/local."


def proxy_root(settings=None) -> str:
    return os.environ.get("VUXGM_CREDIT_API_BASE", "").rstrip("/")


def license_key() -> str:
    try:
        from .vuxgm_license import get_client

        state = get_client().state or get_client().load_cached(allow_grace=True)
        return state.key if state else ""
    except Exception:
        return ""


def credit_on(settings=None) -> bool:
    # Explicit opt-in only.  The adapter stays off until the VuxGM web API is
    # implemented, so no legacy credit endpoint can be contacted accidentally.
    return os.environ.get("VUXGM_CREDIT_ENABLED", "0") == "1" and bool(proxy_root(settings))


def active_provider(settings=None) -> str:
    return "vuxgm" if credit_on(settings) else "byok"


def gemini_endpoint(settings=None, fallback_key: str = "") -> tuple[str, str]:
    return _GOOGLE_NATIVE, str(fallback_key or "")


def openai_base(settings=None, fallback_base: str = "") -> str:
    return str(fallback_base or "").rstrip("/")


def openai_key(settings=None, fallback_key: str = "") -> str:
    return str(fallback_key or "")


def glm_endpoint(settings=None) -> tuple[str, str]:
    base = str(getattr(settings, "glm_base_url", "") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
    key = str(getattr(settings, "glm_api_key", "") or "")
    return base, key


def reset_session() -> None:
    return None


def balance_status(timeout: int = 12) -> tuple[Optional[dict], str]:
    if not license_key():
        return None, BAL_NO_LICENSE
    # Deliberately do not invent a balance or call the old credit service.
    return None, BAL_OFFLINE


def balance(timeout: int = 12) -> Optional[dict]:
    data, status = balance_status(timeout=timeout)
    return data if status == BAL_OK else None
