from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .config import APP_API_BASE, APP_VERSION, LICENSE_PUBLIC_KEY_B64, app_data_dir


API_TIMEOUT_SECONDS = 12
HEARTBEAT_SECONDS = 4 * 60
CACHE_NAME = "license.dat"
MACHINE_ID_NAME = "machine_id.txt"


class LicenseError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, network: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.network = network


@dataclass(frozen=True)
class LicenseState:
    key: str
    machine_id: str
    payload: dict[str, Any]
    signature: str
    offline: bool = False

    @property
    def expires_at(self) -> str:
        return str(self.payload.get("expires_at") or "")

    @property
    def product(self) -> str:
        return str(self.payload.get("product") or "")

    @property
    def plan(self) -> str:
        return str(self.payload.get("plan") or "")


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _parse_iso(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception as exc:
        raise LicenseError("License chứa thời gian không hợp lệ.") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clean_hw(value: str) -> str:
    value = (value or "").strip().replace("\x00", "")
    if value.lower() in {"", "none", "unknown", "default string", "to be filled by o.e.m."}:
        return ""
    return value


def _run_hidden(args: list[str]) -> str:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "timeout": 6,
        "encoding": "utf-8",
        "errors": "ignore",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(args, **kwargs)
        return (proc.stdout or "").strip() if proc.returncode == 0 else ""
    except Exception:
        return ""


def _windows_machine_guid() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, access) as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return _clean_hw(str(value))
    except Exception:
        return ""


def _cim_serial(class_name: str) -> str:
    if sys.platform != "win32":
        return ""
    script = (
        f"(Get-CimInstance -ClassName {class_name} -ErrorAction SilentlyContinue | "
        "Select-Object -First 1 -ExpandProperty SerialNumber)"
    )
    out = _run_hidden([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script
    ])
    return _clean_hw(out.splitlines()[0] if out else "")


def get_machine_id() -> str:
    """Return one stable SHA-256 id and reuse it for activate/refresh/heartbeat/logout."""
    target = app_data_dir() / MACHINE_ID_NAME
    try:
        old = target.read_text(encoding="utf-8").strip().lower()
        if len(old) == 64 and all(ch in "0123456789abcdef" for ch in old):
            return old
    except Exception:
        pass

    if sys.platform == "win32":
        parts = [_windows_machine_guid(), _cim_serial("Win32_BIOS"), _cim_serial("Win32_BaseBoard")]
    else:
        parts = [platform.node(), platform.machine(), str(getattr(os, "getuid", lambda: "")())]

    source = "|".join(_clean_hw(str(x)) for x in parts)
    if not source.strip("|"):
        source = f"{socket.gethostname()}|{platform.platform()}|{app_data_dir()}"
    value = hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()
    try:
        target.write_text(value, encoding="utf-8")
    except Exception:
        pass
    return value


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _to_blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
    buf = (ctypes.c_ubyte * max(1, len(data)))()
    if data:
        ctypes.memmove(buf, data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return b"PLAIN1:" + data
    src, keep = _to_blob(data)
    dst = _DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(src), "VuxGM license", None, None, None, 0x1, ctypes.byref(dst)
    )
    _ = keep
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        if not data.startswith(b"PLAIN1:"):
            raise LicenseError("Không đọc được cache license.")
        return data[7:]
    src, keep = _to_blob(data)
    dst = _DATA_BLOB()
    desc = wintypes.LPWSTR()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(src), ctypes.byref(desc), None, None, None, 0x1, ctypes.byref(dst)
    )
    _ = keep
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(dst.pbData, dst.cbData)
    finally:
        if desc:
            ctypes.windll.kernel32.LocalFree(desc)
        ctypes.windll.kernel32.LocalFree(dst.pbData)


def _platform_label() -> str:
    if sys.platform == "win32":
        return f"Windows {platform.release()} {platform.machine()}".strip()
    return f"{platform.system()} {platform.release()} {platform.machine()}".strip()


def _machine_name() -> str:
    return os.environ.get("COMPUTERNAME") or socket.gethostname() or "Unknown"


class LicenseClient:
    def __init__(self, *, api_base: str = APP_API_BASE, public_key_b64: str = LICENSE_PUBLIC_KEY_B64) -> None:
        self.api_base = api_base.rstrip("/")
        self.public_key_b64 = (public_key_b64 or "").strip()
        self.machine_id = get_machine_id()
        self.state: LicenseState | None = None
        self.last_server_time: datetime | None = None
        self._lock = threading.RLock()

    @property
    def cache_path(self) -> Path:
        return app_data_dir() / CACHE_NAME

    def _device_body(self, key: str) -> dict[str, str]:
        return {
            "license_key": key.strip().upper(),
            "machine_id": self.machine_id,
            "machine_name": _machine_name(),
            "app_version": APP_VERSION,
            "platform": _platform_label(),
        }

    def _request(self, path: str, *, method: str = "GET", body: Any = None) -> dict[str, Any]:
        url = f"{self.api_base}/{path.lstrip('/')}"
        raw_body = None
        headers = {"Accept": "application/json"}
        if body is not None:
            raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=raw_body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=API_TIMEOUT_SECONDS, context=ssl.create_default_context()) as res:
                raw = res.read().decode("utf-8", errors="replace")
                data = json.loads(raw) if raw else {}
                if not isinstance(data, dict):
                    raise LicenseError("Server trả dữ liệu không hợp lệ.")
                return data
        except urllib.error.HTTPError as exc:
            message = f"Lỗi HTTP {exc.code}"
            try:
                data = json.loads(exc.read().decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    message = str(data.get("statusMessage") or data.get("message") or message)
            except Exception:
                pass
            raise LicenseError(message, status_code=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LicenseError("Không kết nối được máy chủ license.", network=True) from exc
        except json.JSONDecodeError as exc:
            raise LicenseError("Server trả JSON không hợp lệ.") from exc

    def _public_key(self) -> Ed25519PublicKey:
        if not self.public_key_b64:
            raise LicenseError(
                "App chưa nhúng Ed25519 public key của VuxGM. "
                "Hãy đặt VUXGM_LICENSE_PUBLIC_KEY trước khi build EXE."
            )
        try:
            raw = base64.b64decode(self.public_key_b64, validate=True)
            if len(raw) != 32:
                raise ValueError
            return Ed25519PublicKey.from_public_bytes(raw)
        except Exception as exc:
            raise LicenseError("Ed25519 public key trong app không hợp lệ.") from exc

    def verify_signature(self, payload: dict[str, Any], signature_b64: str) -> None:
        try:
            signature = base64.b64decode(signature_b64, validate=True)
            self._public_key().verify(signature, canonical_payload(payload))
        except InvalidSignature as exc:
            raise LicenseError("Chữ ký license không hợp lệ.") from exc
        except LicenseError:
            raise
        except Exception as exc:
            raise LicenseError("Không xác minh được chữ ký license.") from exc

    def validate(self, payload: dict[str, Any], signature: str, key: str, *, allow_grace: bool) -> LicenseState:
        self.verify_signature(payload, signature)
        key = key.strip().upper()
        if str(payload.get("key") or "").strip().upper() != key:
            raise LicenseError("Key trong payload không khớp.")
        if str(payload.get("machine_id") or "").strip().lower() != self.machine_id.lower():
            raise LicenseError("License không thuộc máy này.")

        now = self.last_server_time or datetime.now(timezone.utc)
        expires_at = _parse_iso(payload.get("expires_at"))
        token_exp = _parse_iso(payload.get("token_exp"))
        if expires_at <= now:
            raise LicenseError("License đã hết hạn.")

        offline = False
        if token_exp <= now:
            grace_days = max(0, int(payload.get("grace_days") or 0))
            if not allow_grace or now > token_exp + timedelta(days=grace_days):
                raise LicenseError("Phiên license đã hết hạn, cần kết nối Internet để refresh.")
            offline = True

        return LicenseState(key, self.machine_id, dict(payload), signature, offline)

    def _save(self, state: LicenseState) -> None:
        raw = json.dumps(
            {"key": state.key, "machine_id": state.machine_id, "payload": state.payload, "signature": state.signature},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.cache_path.write_bytes(_protect(raw))

    def clear_local(self) -> None:
        self.state = None
        try:
            self.cache_path.unlink(missing_ok=True)
        except Exception:
            pass

    def load_cached(self, *, allow_grace: bool = True) -> LicenseState | None:
        if not self.cache_path.exists():
            return None
        try:
            data = json.loads(_unprotect(self.cache_path.read_bytes()).decode("utf-8"))
            key = str(data.get("key") or "").strip().upper()
            if str(data.get("machine_id") or "").lower() != self.machine_id.lower():
                raise LicenseError("Cache license thuộc máy khác.")
            state = self.validate(dict(data.get("payload") or {}), str(data.get("signature") or ""), key, allow_grace=allow_grace)
            self.state = state
            return state
        except Exception:
            self.clear_local()
            return None

    def _accept(self, data: dict[str, Any], key: str) -> LicenseState:
        payload = data.get("payload")
        signature = str(data.get("signature") or "")
        if not isinstance(payload, dict) or not signature:
            raise LicenseError("Server không trả payload/signature.")
        state = self.validate(payload, signature, key, allow_grace=False)
        self.state = state
        self._save(state)
        return state

    def activate(self, key: str) -> LicenseState:
        key = key.strip().upper()
        if not key:
            raise LicenseError("Hãy nhập license key.")
        with self._lock:
            return self._accept(self._request("license/activate", method="POST", body=self._device_body(key)), key)

    def refresh(self, key: str | None = None) -> LicenseState:
        with self._lock:
            use_key = (key or (self.state.key if self.state else "")).strip().upper()
            if not use_key:
                cached = self.load_cached(allow_grace=True)
                use_key = cached.key if cached else ""
            if not use_key:
                raise LicenseError("Chưa có license key.")
            return self._accept(self._request("license/refresh", method="POST", body=self._device_body(use_key)), use_key)

    def startup(self) -> LicenseState | None:
        cached = self.load_cached(allow_grace=True)
        if not cached:
            return None
        try:
            return self.refresh(cached.key)
        except LicenseError as exc:
            if exc.network:
                cached = self.load_cached(allow_grace=True)
                if cached:
                    self.state = LicenseState(cached.key, cached.machine_id, cached.payload, cached.signature, True)
                    return self.state
            if exc.status_code in {400, 403, 404, 409}:
                self.clear_local()
            raise

    def heartbeat(self) -> dict[str, Any]:
        with self._lock:
            state = self.state or self.load_cached(allow_grace=True)
            if not state:
                raise LicenseError("Chưa có license để heartbeat.")
            data = self._request("license/heartbeat", method="POST", body=self._device_body(state.key))
            if data.get("serverTime"):
                try:
                    self.last_server_time = _parse_iso(data["serverTime"])
                except LicenseError:
                    pass
            return data

    def logout(self) -> bool:
        with self._lock:
            state = self.state or self.load_cached(allow_grace=True)
            if not state:
                self.clear_local()
                return True
            data = self._request(
                "license/logout",
                method="POST",
                body={"license_key": state.key, "machine_id": self.machine_id},
            )
            released = bool(data.get("released"))
            if released:
                self.clear_local()
            return released

    def latest_download_url(self) -> str:
        return f"{self.api_base}/download/latest"

    def status_text(self) -> str:
        if not self.state:
            return "Chưa kích hoạt"
        mode = "OFFLINE GRACE" if self.state.offline else "Online"
        return f"{self.state.product or 'VuxGM'} · {self.state.plan or 'license'} · {mode} · hết hạn {self.state.expires_at}"
