from __future__ import annotations

from datetime import datetime
import os
import webbrowser

from .vuxgm_config import APP_SITE_URL


NHAC_TRUOC_NGAY = 3


def hint_on() -> bool:
    return os.environ.get("VUXGM_LICENSE_HINT_OFF", "").strip() != "1"


def giahan_url(key: str = "") -> str:
    # Do not put the license key in a query string.  The VuxGM site can handle
    # account/key management after the user opens it.
    return APP_SITE_URL


def nen_nhac(days_left, da_nhac: bool, busy: bool) -> bool:
    if not hint_on() or da_nhac or busy:
        return False
    try:
        return days_left is not None and 0 <= int(days_left) <= NHAC_TRUOC_NGAY
    except Exception:
        return False


def la_key_ngan(issued_at, expires_at, tran_ngay: int = 4) -> bool:
    def _p(value):
        return datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))

    if not issued_at or not expires_at:
        return False
    try:
        return (_p(expires_at) - _p(issued_at)).total_seconds() <= int(tran_ngay) * 86400
    except Exception:
        return False


def mo_web_giahan(key: str = "") -> bool:
    try:
        return bool(webbrowser.open(giahan_url(key)))
    except Exception:
        return False
