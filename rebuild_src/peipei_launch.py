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

    # The clean rebuild uses the user's own VuxGM license service. It is kept
    # separate from the extracted application's original third-party licensing.
    from bilisub.gui.licensed_main import main as gui_main

    return int(gui_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
