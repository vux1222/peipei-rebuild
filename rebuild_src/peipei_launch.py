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

    # Use the original Python 3.13 bytecode as the behavioral baseline while the
    # source is reconstructed module-by-module.  VuxGM license/branding/credit
    # adapters are injected before any legacy module is imported.
    from bilisub.gui.legacy_licensed_main import main as gui_main

    return int(gui_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
