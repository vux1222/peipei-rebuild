from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REBUILD_SRC = ROOT / "rebuild_src"
if str(REBUILD_SRC) not in sys.path:
    sys.path.insert(0, str(REBUILD_SRC))

from bilisub.ffmpeg_utils import target_resolution
from bilisub.models import SubtitleEntry
from bilisub.srt import export_srt, parse_srt


class SubtitleEntryTests(unittest.TestCase):
    def test_time_roundtrip(self) -> None:
        value = SubtitleEntry.parse_time("01:02:03,456")
        self.assertEqual(value, 3_723_456)
        self.assertEqual(SubtitleEntry.format_time(value), "01:02:03,456")

    def test_output_text_prefers_translation(self) -> None:
        entry = SubtitleEntry(text="hello", translated="xin chào")
        self.assertEqual(entry.output_text, "xin chào")
        self.assertEqual(entry.speak_text, "xin chào")


class FfmpegUtilsTests(unittest.TestCase):
    def test_target_resolution_landscape_is_even(self) -> None:
        width, height = target_resolution(1920, 1080, 720)
        self.assertEqual(height, 720)
        self.assertEqual(width % 2, 0)
        self.assertEqual(height % 2, 0)

    def test_target_resolution_invalid_input(self) -> None:
        self.assertEqual(target_resolution(0, 0), (1920, 1080))


class SrtTests(unittest.TestCase):
    def test_parse_export_roundtrip(self) -> None:
        source = """1
00:00:00,500 --> 00:00:02,000
Xin chào

2
00:00:02,100 --> 00:00:03,500
Thế giới
"""
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.srt"
            out = Path(td) / "out.srt"
            src.write_text(source, encoding="utf-8")
            entries = parse_srt(src)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].text, "Xin chào")
            export_srt(entries, out, use_translated=False)
            entries2 = parse_srt(out)
            self.assertEqual([e.text for e in entries2], ["Xin chào", "Thế giới"])


if __name__ == "__main__":
    unittest.main()
