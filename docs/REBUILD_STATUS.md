# PeiPei rebuild status

This branch is a clean rebuild workspace. The original extracted `.pyc` files remain untouched on `main`/as reference material.

## Confirmed architecture

- Python 3.13, 64-bit runtime.
- PyInstaller launcher imports `bilisub.gui.main_window.main`.
- Core workflow is coordinated by `bilisub.pipeline`.
- GUI uses PyQt6.
- Video/audio processing depends on FFmpeg/FFprobe and PyAV.
- ASR uses faster-whisper/CTranslate2.
- OCR uses RapidOCR/ONNX Runtime.
- TTS/runtime assets include Edge TTS, VieNeu and SEA G2P components.

## Current reconstructed files

- `rebuild_src/peipei_launch.py`
- `rebuild_src/bilisub/__init__.py`
- `tools/check_runtime.py`

## Next source modules to reconstruct

1. `bilisub/config.py`
2. `bilisub/ffmpeg_utils.py`
3. `bilisub/srt.py`
4. `bilisub/pipeline.py`
5. `bilisub/gui/main_window.py`

The large GUI/pipeline modules should be reconstructed from their disassembly text rather than guessed from bytecode metadata alone.

## Runtime policy

Keep the original `_internal` directory local for the first rebuild. It contains ABI-sensitive Python 3.13 native extensions, Qt DLLs, codecs, ONNX/CUDA providers, models and voice assets. Do not trim it until a baseline rebuild runs successfully.

The rebuild work does not remove, bypass, or replace third-party commercial licensing controls.
