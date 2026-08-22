from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .models import SubtitleEntry


class ASRError(RuntimeError):
    pass


class WhisperASR:
    """Small faster-whisper wrapper matching the interface used by the pipeline.

    The original application creates ``WhisperASR(model, device, compute_type,
    log=...)`` and calls ``transcribe(path, language=..., progress=...)``. This
    reconstruction keeps that contract so the larger pipeline can be restored
    incrementally without changing callers.
    """

    def __init__(
        self,
        model: str = "large-v3",
        device: str = "auto",
        compute_type: str = "auto",
        *,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.model_name = model or "large-v3"
        self.device = device or "auto"
        self.compute_type = compute_type or "auto"
        self.log = log
        self._model = None
        self.detected_language: Optional[str] = None

    def _say(self, text: str) -> None:
        if self.log:
            self.log(text)

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - runtime dependency
            raise ASRError(
                "Thiếu faster-whisper. Hãy dùng runtime gốc hoặc cài faster-whisper trước khi chạy ASR."
            ) from exc

        kwargs = {"device": self.device}
        if self.compute_type and self.compute_type != "auto":
            kwargs["compute_type"] = self.compute_type

        self._say(f"🎙 Nạp Whisper model {self.model_name} ({self.device}/{self.compute_type})…")
        try:
            self._model = WhisperModel(self.model_name, **kwargs)
        except Exception as first_exc:
            # Automatic GPU setups can fail because CUDA DLLs are absent or an
            # unsupported compute type was selected. A CPU fallback makes the
            # clean rebuild usable while preserving an explicit log message.
            if self.device in {"auto", "cuda"}:
                self._say(f"⚠ Không nạp được Whisper trên {self.device}: {first_exc}. Thử CPU int8…")
                try:
                    self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
                except Exception as second_exc:
                    raise ASRError(f"Không nạp được Whisper model {self.model_name}: {second_exc}") from second_exc
            else:
                raise ASRError(f"Không nạp được Whisper model {self.model_name}: {first_exc}") from first_exc
        return self._model

    def transcribe(
        self,
        media_path: str | Path,
        *,
        language: Optional[str] = "auto",
        progress: Optional[Callable[[int], None]] = None,
    ) -> list[SubtitleEntry]:
        path = Path(media_path)
        if not path.exists():
            raise ASRError(f"Không tìm thấy file cho ASR: {path}")

        model = self._load()
        lang = None if not language or str(language).lower() == "auto" else str(language).lower()

        try:
            segments, info = model.transcribe(
                str(path),
                language=lang,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=True,
            )
        except Exception as exc:
            raise ASRError(f"Whisper transcribe thất bại: {exc}") from exc

        self.detected_language = getattr(info, "language", None) or lang
        if self.detected_language:
            probability = getattr(info, "language_probability", None)
            if probability is not None:
                self._say(f"🌐 Whisper nhận diện ngôn ngữ: {self.detected_language} ({probability:.1%})")
            else:
                self._say(f"🌐 Whisper ngôn ngữ: {self.detected_language}")

        total_s = float(getattr(info, "duration", 0.0) or getattr(info, "duration_after_vad", 0.0) or 0.0)
        entries: list[SubtitleEntry] = []
        for index, segment in enumerate(segments, 1):
            text = " ".join(str(getattr(segment, "text", "") or "").split()).strip()
            if not text:
                continue
            start_ms = max(0, round(float(segment.start) * 1000))
            end_ms = max(start_ms + 1, round(float(segment.end) * 1000))
            entries.append(SubtitleEntry(index=len(entries) + 1, start_ms=start_ms, end_ms=end_ms, text=text))

            if progress and total_s > 0:
                try:
                    progress(min(99, max(0, int(float(segment.end) * 100 / total_s))))
                except Exception:
                    pass

        if progress:
            try:
                progress(100)
            except Exception:
                pass

        if not entries:
            raise ASRError("Whisper chạy xong nhưng không nhận được câu thoại nào.")
        self._say(f"✓ Whisper tạo {len(entries)} câu thoại.")
        return entries
