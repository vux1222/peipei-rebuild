from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .license_bootstrap import get_license_public_key
from .license_client import LicenseClient, LicenseError, LicenseState


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


def activate(key: str) -> dict[str, Any]:
    global _last_error
    try:
        st = get_client().activate(key)
        _last_error = ""
        return {"status": "VALID", "payload": st.payload, "expires_at": st.expires_at}
    except LicenseError as exc:
        _last_error = str(exc)
        return {"status": "INVALID", "message": str(exc)}


def maybe_refresh(force: bool = False) -> dict[str, Any] | None:
    global _last_error
    c = get_client()
    try:
        if force:
            st = c.refresh()
        else:
            st = c.startup()
        _last_error = ""
        if st is None:
            return None
        return {"status": "GRACE" if st.offline else "VALID", "payload": st.payload, "expires_at": st.expires_at}
    except LicenseError as exc:
        _last_error = str(exc)
        if exc.network:
            cached = c.load_cached(allow_grace=True)
            if cached is not None:
                return {"status": "GRACE", "payload": cached.payload, "expires_at": cached.expires_at}
        return None


def check() -> dict[str, Any]:
    global _last_error
    try:
        st = _state()
    except LicenseError as exc:
        _last_error = str(exc)
        return {"status": "INVALID", "message": str(exc)}
    if st is None:
        return {"status": "MISSING", "message": _last_error or "Chưa kích hoạt license."}
    return {
        "status": "GRACE" if st.offline else "VALID",
        "payload": st.payload,
        "expires_at": st.expires_at,
        "plan": st.plan,
        "product": st.product,
    }


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

    The old updater expected a PeiPei manifest shape. VuxGM's download endpoint is
    different, so automatic replacement is disabled until the VuxGM manifest API
    is finalized. Returning None keeps the old UI silent and safe.
    """
    return None


def logout() -> bool:
    return get_client().logout()
