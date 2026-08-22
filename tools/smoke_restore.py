from __future__ import annotations

import sys
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "rebuild_src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    try:
        from bilisub.legacy_bridge import prepare_legacy_runtime

        paths, legacy_main = prepare_legacy_runtime()
        import bilisub

        print("[OK] Python:", sys.version.split()[0])
        print("[OK] PYZ:", paths.pyz_root)
        print("[OK] _internal:", paths.internal_root)
        print("[OK] MainWindow:", legacy_main.MainWindow)
        print("[OK] APP_VERSION:", getattr(bilisub.config, "APP_VERSION", "?"))
        print("[OK] license module:", getattr(bilisub.license_client, "__file__", "<facade>"))
        print("[OK] credit module:", getattr(bilisub.credit, "__file__", "<adapter>"))
        print("[OK] renewal module:", getattr(bilisub.giahan, "__file__", "<adapter>"))
        print("\nLegacy runtime bridge nạp thành công.")
        return 0
    except Exception:
        print("\n[FAIL] Không nạp được restored runtime:\n", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
