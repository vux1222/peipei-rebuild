from __future__ import annotations

import multiprocessing
import sys


def _run_voice_self_test() -> int:
    """Placeholder for the optional Vietnamese voice self-test."""
    print("Voice self-test scaffold: implementation pending reconstructed runtime code.")
    return 0


def main() -> int:
    multiprocessing.freeze_support()

    if "--tu-kiem-giong" in sys.argv:
        return _run_voice_self_test()

    # Public product version shown by the app and sent to the VuxGM license API.
    # Keep legacy internal paths untouched so existing settings/license cache continue to work.
    from bilisub import config as app_config

    app_config.APP_VERSION = "1.0.0"

    from bilisub.gui.licensed_main import main as gui_main

    return int(gui_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
