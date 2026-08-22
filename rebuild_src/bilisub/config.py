from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    base_url: str
    default_model: str
    needs_key: bool = True


GEMINI_TRANSLATE_MODEL = "gemini-flash-lite-latest"
GEMINI_VISION_MODEL = "gemini-3.5-flash"
DEEPSEEK_TRANSLATE_MODEL = "deepseek-v4-flash"
DEEPSEEK_VISION_MODEL = "deepseek-v4-flash"

DEAD_MODEL_MAP = {
    "gemini-2.5-flash-lite": GEMINI_TRANSLATE_MODEL,
    "gemini-2.5-flash-lite-preview": GEMINI_TRANSLATE_MODEL,
    "gemini-2.5-flash": GEMINI_VISION_MODEL,
    "gemini-1.5-flash": GEMINI_VISION_MODEL,
    "gemini-1.5-flash-latest": GEMINI_VISION_MODEL,
    "deepseek-chat": DEEPSEEK_TRANSLATE_MODEL,
    "deepseek-reasoner": DEEPSEEK_TRANSLATE_MODEL,
}

LLM_PROVIDERS: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec("gemini", "Gemini API", "https://generativelanguage.googleapis.com/v1beta/openai", GEMINI_TRANSLATE_MODEL),
    "deepseek": ProviderSpec("deepseek", "DeepSeek API", "https://api.deepseek.com/v1", DEEPSEEK_TRANSLATE_MODEL),
    "groq": ProviderSpec("groq", "Groq API", "https://api.groq.com/openai/v1", "qwen/qwen3-32b"),
    "cerebras": ProviderSpec("cerebras", "Cerebras API", "https://api.cerebras.ai/v1", "llama3.1-8b"),
    "sambanova": ProviderSpec("sambanova", "SambaNova Cloud", "https://api.sambanova.ai/v1", "DeepSeek-V3.2"),
    "openrouter": ProviderSpec("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "openrouter/free"),
    "lmstudio": ProviderSpec("lmstudio", "LM Studio (local)", "http://localhost:1234/v1", "local-model", False),
    "ollama": ProviderSpec("ollama", "Ollama (local)", "http://localhost:11434/v1", "qwen2.5:7b", False),
    "custom": ProviderSpec("custom", "Custom OpenAI-compatible", "", "", False),
}

LOCAL_PROVIDERS = {"lmstudio", "ollama"}
DEFAULT_FALLBACK_ORDER = ["gemini", "groq", "cerebras", "sambanova", "openrouter", "ollama", "lmstudio"]

LANGUAGES = {
    "auto": "Tự động nhận diện",
    "zh": "Tiếng Trung",
    "vi": "Tiếng Việt",
    "en": "Tiếng Anh",
    "ja": "Tiếng Nhật",
    "ko": "Tiếng Hàn",
    "th": "Tiếng Thái",
    "fr": "Tiếng Pháp",
    "de": "Tiếng Đức",
    "es": "Tiếng Tây Ban Nha",
    "pt": "Tiếng Bồ Đào Nha",
    "id": "Tiếng Indonesia",
    "hi": "Tiếng Hindi (Ấn Độ)",
    "bn": "Tiếng Bengali",
    "ta": "Tiếng Tamil",
    "te": "Tiếng Telugu",
    "mr": "Tiếng Marathi",
    "gu": "Tiếng Gujarati",
    "kn": "Tiếng Kannada",
    "ml": "Tiếng Malayalam",
    "ur": "Tiếng Urdu",
    "ar": "Tiếng Ả Rập",
}

# User-owned deployment/site for this clean rebuild. This is deliberately separate
# from the extracted application's third-party licensing implementation.
APP_SITE_URL = os.environ.get("VUXGM_SITE_URL", "https://vuxgm.site").rstrip("/")
APP_API_BASE = os.environ.get("VUXGM_API_BASE", f"{APP_SITE_URL}/api").rstrip("/")
APP_VERSION = "1.5.72-rebuild"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    # Keep clean-rebuild settings isolated from the extracted application's data.
    d = Path(base) / "VuxGM" / "PeiPeiRebuild"
    d.mkdir(parents=True, exist_ok=True)
    return d


_TEMP_MIN_GB = 12.0


def _la_o_mang(path: str) -> bool:
    try:
        p = str(path or "")
        if not p:
            return False
        if p.startswith("\\\\") or p.startswith("//"):
            return True
        drv = os.path.splitdrive(os.path.abspath(p))[0]
        if not drv or sys.platform != "win32":
            return False
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(drv + "\\")) == 4
    except Exception:
        return False


def _noi_bo_du_cho(min_gb: float = _TEMP_MIN_GB) -> bool:
    try:
        return shutil.disk_usage(tempfile.gettempdir()).free >= min_gb * 1024**3
    except Exception:
        return False


def temp_base_dir(settings: Optional["Settings"] = None, video_path: str = "", *, log=None) -> str:
    candidates: list[str] = []
    if settings is not None:
        out_dir = str(getattr(settings, "video_output_dir", "") or "").strip()
        if out_dir:
            candidates.append(out_dir)
    if video_path:
        try:
            candidates.append(str(Path(video_path).resolve().parent))
        except Exception:
            pass

    allow_network = os.environ.get("BILISUB_TEMP_O_MANG") == "1"
    for base in candidates:
        try:
            if not allow_network and _la_o_mang(base) and _noi_bo_du_cho():
                if log:
                    log(f"ℹ Thư mục lưu video nằm trên ổ mạng ({str(base)[:40]}…) — dùng ổ tạm trong máy để tránh gián đoạn.")
                continue
            d = Path(base) / "peipei_temp"
            d.mkdir(parents=True, exist_ok=True)
            test = d / ".wtest"
            test.write_bytes(b"x")
            test.unlink()
            return str(d)
        except Exception:
            continue
    return tempfile.gettempdir()


def pack_root() -> Path:
    try:
        f = app_data_dir() / "pack_dir.txt"
        if f.exists():
            p = (f.read_text(encoding="utf-8") or "").strip()
            if p:
                return Path(p)
    except Exception:
        pass
    return app_data_dir()


def set_pack_root(path: str) -> Path:
    default = app_data_dir()
    f = default / "pack_dir.txt"
    p = (path or "").strip()
    if not p:
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
        return default
    try:
        pd = Path(p)
        pd.mkdir(parents=True, exist_ok=True)
        test = pd / ".peipei_write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink(missing_ok=True)
        f.write_text(str(pd), encoding="utf-8")
        return pd
    except Exception:
        return pack_root()


def default_videos_dir(sub: str = "") -> Path:
    base = os.environ.get("USERPROFILE") or str(Path.home())
    candidates = [Path(base) / "Videos" / "PeiPeiRebuild", app_data_dir() / "Videos"]
    for candidate in candidates:
        try:
            d = candidate / sub if sub else candidate
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            continue
    return Path(tempfile.gettempdir())


def default_settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return app_data_dir() / "settings.json"
    local = Path.cwd() / "settings.json"
    return local if local.exists() else app_data_dir() / "settings.json"


COVER_PAD_LEVELS: dict[str, float] = {"tight": 0.22, "medium": 0.30, "wide": 0.42}
COVER_PAD_LABELS: dict[str, str] = {"tight": "Bó sát (gọn nhất)", "medium": "Vừa", "wide": "Rộng (che chắc)"}
COVER_PAD_DEFAULT = "tight"
COVER_PAD_K_MIN, COVER_PAD_K_MAX = 0.0, 1.0
COVER_PAD_FLOOR_PX = 4.0


def cover_pad_k(settings: Any) -> float:
    level = str(getattr(settings, "cover_pad_level", "") or "").strip().lower()
    k = COVER_PAD_LEVELS.get(level)
    if k is None:
        k = COVER_PAD_LEVELS[COVER_PAD_DEFAULT]
    return max(COVER_PAD_K_MIN, min(COVER_PAD_K_MAX, float(k)))


def cover_pad_norm(text_h_norm: float, k: float, frame_w: int, frame_h: int) -> tuple[float, float]:
    width = max(1, int(frame_w or 0) or 1920)
    height = max(1, int(frame_h or 0) or 1080)
    h = max(0.0, float(text_h_norm or 0.0))
    pad_px = max(float(k) * h * height, COVER_PAD_FLOOR_PX)
    pad_px = min(pad_px, 0.15 * height)
    return pad_px / width, pad_px / height


@dataclass
class Settings:
    """Reconstructed settings surface.

    The original class is very large. These fields cover the core pipeline/UI now;
    unknown keys are retained in ``extra`` so older settings files can round-trip
    while more fields are reconstructed.
    """

    api_keys: dict[str, str] = field(default_factory=dict)
    provider: str = "gemini"
    ai_provider: str = "gemini"
    custom_base_url: str = ""
    custom_model: str = ""
    provider_models: dict[str, str] = field(default_factory=dict)
    source_mode: str = "auto"
    source_language: str = "auto"
    subtitle_language: str = "vi"
    voice_language: str = "vi"
    asr_model: str = "large-v3"
    asr_device: str = "auto"
    asr_compute_type: str = "auto"
    tts_voice: str = ""
    tts_speed: float = 1.0
    video_speed: float = 1.0
    original_volume: float = 1.0
    video_output_dir: str = ""
    output_short_side: int = 1080
    subtitle_preset: str = "Classic"
    ass_font: str = "Arial"
    ass_font_size: int = 54
    subtitle_position: str = "bottom"
    cover_mode: str = "none"
    cover_pad_level: str = COVER_PAD_DEFAULT
    preview_time: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def get_key(self, provider: str) -> str:
        return str(self.api_keys.get(provider, "") or "")

    def model_for(self, provider: str) -> str:
        if provider in self.provider_models and self.provider_models[provider]:
            return self.provider_models[provider]
        spec = LLM_PROVIDERS.get(provider)
        return spec.default_model if spec else self.custom_model

    def base_url_for(self, provider: str) -> str:
        if provider == "custom":
            return self.custom_base_url
        spec = LLM_PROVIDERS.get(provider)
        return spec.base_url if spec else ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        extra = data.pop("extra", {})
        data.update(extra)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)} - {"extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        obj = cls(**kwargs)
        obj.extra = {k: v for k, v in data.items() if k not in known}
        return obj

    def save(self, path: str | Path | None = None) -> Path:
        target = Path(path) if path else default_settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        target = Path(path) if path else default_settings_path()
        if not target.exists():
            return cls()
        try:
            return cls.from_dict(json.loads(target.read_text(encoding="utf-8-sig")))
        except Exception:
            return cls()
