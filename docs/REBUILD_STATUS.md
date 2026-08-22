# PeiPei rebuild status

This branch is a clean, editable rebuild workspace. The extracted `.pyc` files remain untouched as reference material.

## Confirmed architecture

- Python 3.13, 64-bit runtime.
- PyInstaller launcher imports `bilisub.gui.main_window.main`.
- Core workflow is coordinated by `bilisub.pipeline`.
- GUI uses PyQt6.
- Video/audio processing depends on FFmpeg/FFprobe and PyAV.
- ASR uses faster-whisper/CTranslate2.
- OCR uses RapidOCR/ONNX Runtime.
- TTS/runtime assets include Edge TTS, VieNeu and SEA G2P components.

## Current reconstructed source

- `rebuild_src/peipei_launch.py`
- `rebuild_src/bilisub/config.py`
- `rebuild_src/bilisub/models.py`
- `rebuild_src/bilisub/ffmpeg_utils.py`
- `rebuild_src/bilisub/srt.py`
- `rebuild_src/bilisub/pipeline.py`
- `rebuild_src/bilisub/gui/main_window.py`
- `tools/check_runtime.py`

## Runnable baseline

The current GUI/pipeline supports an existing SRT file through these stages:

`video + SRT -> parse/clean -> merge short cues -> export SRT/ASS -> FFmpeg render`

It also supports FFprobe video inspection and preview trimming. The GUI intentionally leaves ASR/OCR, AI translation and TTS disabled until their source modules are reconstructed.

## Clean rebuild website

The user-owned project domain is configured as:

- `VUXGM_SITE_URL=https://vuxgm.site`
- `VUXGM_API_BASE=https://vuxgm.site/api`

These values are for the clean rebuild website/API and are deliberately separate from third-party licensing code in the extracted reference application.

## Next source modules to reconstruct

1. `bilisub/asr.py` and hard-sub/OCR dispatch.
2. `bilisub/translate/*` translation providers and tiered orchestration.
3. `bilisub/tts/*` engine abstraction and selected TTS backends.
4. `bilisub/render.py` and advanced output options.
5. Advanced ASS/art-text layout from `bilisub/srt.py` and GUI controls from the large original window.

## Runtime policy

Keep the original `_internal` directory local for the first rebuild. It contains ABI-sensitive Python 3.13 native extensions, Qt DLLs, codecs, ONNX/CUDA providers, models and voice assets. Do not trim it until a baseline rebuild runs successfully.

The rebuild work does not remove, bypass, or replace third-party commercial licensing controls.
