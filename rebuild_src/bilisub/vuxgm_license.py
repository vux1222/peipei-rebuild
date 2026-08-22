from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .license_bootstrap import get_license_public_key
from .license_client import LicenseClient, LicenseError, LicenseState, get_machine_id


_client: LicenseClient | None = None
_last_error = ""


def get_client() -> LicenseClient:
    global _client
    if _client is None:
        _client = LicenseClient(public_key_b64=get_license_public_key())
    return _client


def _state() -> LicenseState | None:
    c = get_client()
    return c.state or c.load_cached(allow_grace=True)


def _legacy_status(st: LicenseState) -> dict[str, Any]:
    info = dict(st.payload)
    info.setdefault("expires_at", st.expires_at)
    info.setdefault("plan", st.plan)
    info.setdefault("product", st.product)
    status = "GRACE" if st.offline else "VALID"
    return {
        "status": status,
        "message": "License hợp lệ." if status == "VALID" else "Đang dùng license offline grace.",
        "info": info,
        "payload": info,
        "expires_at": st.expires_at,
    }


def activate(key: str) -> dict[str, Any]:
    global _last_error
    try:
        st = get_client().activate(key)
        _last_error = ""
        return _legacy_status(st)
    except LicenseError as exc:
        _last_error = str(exc)
        return {"status": "INVALID", "message": str(exc), "info": {}}


def refresh() -> dict[str, Any]:
    global _last_error
    try:
        st = get_client().refresh()
        _last_error = ""
        return _legacy_status(st)
    except LicenseError as exc:
        _last_error = str(exc)
        return {"status": "INVALID", "message": str(exc), "info": {}}


def maybe_refresh(force: bool = False) -> dict[str, Any] | None:
    global _last_error
    c = get_client()
    try:
        if force:
            st = c.refresh()
        else:
            st = c.startup()
        _last_error = ""
        return _legacy_status(st) if st is not None else None
    except LicenseError as exc:
        _last_error = str(exc)
        if exc.network:
            cached = c.load_cached(allow_grace=True)
            if cached is not None:
                return _legacy_status(cached)
        return None


def check() -> dict[str, Any]:
    global _last_error
    try:
        st = _state()
    except LicenseError as exc:
        _last_error = str(exc)
        return {"status": "INVALID", "message": str(exc), "info": {}}
    if st is None:
        return {"status": "MISSING", "message": _last_error or "Chưa kích hoạt license.", "info": {}}
    return _legacy_status(st)


def is_active() -> bool:
    return check().get("status") in {"VALID", "GRACE"}


def blocked_reason() -> str:
    if is_active():
        return ""
    return str(check().get("message") or _last_error or "License chưa hợp lệ.")


def days_left() -> int:
    st = _state()
    if st is None or not st.expires_at:
        return 0
    text = st.expires_at
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        exp = datetime.fromisoformat(text)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        seconds = (exp.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        return max(0, int((seconds + 86399) // 86400))
    except Exception:
        return 0


def status_text() -> str:
    try:
        return get_client().status_text()
    except Exception:
        return blocked_reason() or "Chưa kích hoạt"


def check_update() -> dict[str, Any] | None:
    """Legacy UI compatibility.

    The old updater expected a different manifest shape.  Automatic replacement
    stays disabled until the VuxGM update manifest is finalized.
    """
    return None


def logout() -> bool:
    return get_client().logout()


def hw_fingerprint() -> str:
    return get_machine_id()
