# PeiPei Rebuild

This folder is a clean, editable reconstruction workspace. The extracted `.pyc` reference files on `main` are not modified.

## Current working baseline

The current rebuild can:

- launch a PyQt6 desktop window;
- inspect a video with FFprobe;
- import and clean an existing `.srt` file;
- merge very short subtitle cues;
- export SRT and a basic ASS subtitle track;
- create a preview clip;
- render a video with FFmpeg, optionally burning the ASS subtitles;
- open the project website at `https://vuxgm.site`.

ASR/OCR, AI translation, advanced ASS/art-text layout, TTS and the larger production render pipeline are still being reconstructed. The GUI intentionally disables those incomplete stages instead of pretending they work.

## Website / API

The clean rebuild defaults to:

```text
VUXGM_SITE_URL=https://vuxgm.site
VUXGM_API_BASE=https://vuxgm.site/api
```

You can override either value with environment variables. These values belong to this clean rebuild and do not replace or bypass any third-party licensing service from the extracted reference application.

## Run on Windows

Use 64-bit Python 3.13, matching the ABI of the extracted runtime:

```powershell
cd D:\innoextract670\extracted\app\PeiPeiReup.exe_extracted
git fetch origin
git switch rebuild-scaffold
git pull
py -3.13 -m pip install -r rebuild_src\requirements-minimal.txt
py -3.13 rebuild_src\peipei_launch.py
```

The easiest first test is to choose a video plus an existing SRT and click **Chạy**.

## FFmpeg

The rebuild searches for FFmpeg in this order: `BILISUB_FFMPEG`, bundled/frozen locations including `_internal\bin`, the working directory, then `PATH`.

If needed in PowerShell:

```powershell
$env:BILISUB_FFMPEG = "C:\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe"
py -3.13 rebuild_src\peipei_launch.py
```

To inspect the larger original runtime tree before rebuilding more features:

```powershell
$env:PEIPEI_APP_ROOT = "D:\innoextract670\extracted\app"
py -3.13 tools\check_runtime.py
```

## Source layout

```text
rebuild_src/
  peipei_launch.py
  bilisub/
    config.py
    models.py
    ffmpeg_utils.py
    srt.py
    pipeline.py
    gui/
      main_window.py
```

The next reconstruction targets are ASR/OCR, translation, TTS, and the advanced render layer.
