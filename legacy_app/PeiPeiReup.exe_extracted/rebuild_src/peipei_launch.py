from __future__ import annotations

import multiprocessing
import sys


def _run_voice_self_test() -> int:
    """Placeholder for the original optional Vietnamese voice self-test.

    The extracted launcher contains a dedicated self-test path before the GUI starts.
    This rebuild scaffold keeps the command-line hook but intentionally leaves the
    implementation separate until the remaining disassembly/runtime assets are added.
    """
    print("Voice self-test scaffold: implementation pending reconstructed runtime code.")
    return 0


def main() -> int:
    multiprocessing.freeze_support()

    if "--tu-kiem-giong" in sys.argv:
        return _run_voice_self_test()

    from bilisub.gui.main_window import main as gui_main

    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
