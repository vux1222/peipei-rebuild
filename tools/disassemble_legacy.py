from __future__ import annotations

import argparse
import dis
import io
import marshal
import sys
from pathlib import Path
from types import CodeType


def load_pyc(path: Path) -> CodeType:
    raw = path.read_bytes()
    if len(raw) < 16:
        raise ValueError("file .pyc quá ngắn")
    try:
        code = marshal.loads(raw[16:])
    except Exception as exc:
        raise ValueError(
            f"Không đọc được bytecode. Hãy chạy tool bằng đúng Python của app (Python 3.13): {exc}"
        ) from exc
    if not isinstance(code, CodeType):
        raise TypeError("payload .pyc không phải code object")
    return code


def render_code(path: Path, code: CodeType) -> str:
    out = io.StringIO()
    print(f"=== FILE: {path} ===", file=out)
    print(f"python: {sys.version}", file=out)
    print(f"magic: {path.read_bytes()[:4].hex()}", file=out)
    print(file=out)
    # depth=None makes dis recurse through nested classes/functions, preserving
    # the original qualnames, local names, constants and instruction stream.
    dis.dis(code, file=out, depth=None, show_caches=False, adaptive=False)
    return out.getvalue()


def iter_app_pycs(root: Path):
    bilisub = root / "bilisub"
    if not bilisub.is_dir():
        raise FileNotFoundError(f"Không thấy thư mục bilisub tại: {bilisub}")
    yield from sorted(bilisub.rglob("*.pyc"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Disassemble bytecode app cũ để phục dựng source.")
    parser.add_argument("--root", type=Path, required=True, help="Thư mục PYZ..._extracted chứa bilisub/")
    parser.add_argument("--out", type=Path, required=True, help="Thư mục xuất *.dis.txt")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve()
    out_root = args.out.resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    ok = 0
    failed = 0
    for pyc in iter_app_pycs(root):
        rel = pyc.relative_to(root)
        target = out_root / rel.parent / f"{pyc.stem}.dis.txt"
        if target.exists() and not args.overwrite:
            print(f"SKIP {rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            code = load_pyc(pyc)
            target.write_text(render_code(rel, code), encoding="utf-8")
            print(f"OK   {rel} -> {target.relative_to(out_root)}")
            ok += 1
        except Exception as exc:
            print(f"FAIL {rel}: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nHoàn tất: {ok} file OK, {failed} file lỗi")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
