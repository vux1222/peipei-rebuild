from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_VERSION, Settings
from ..ffmpeg_utils import find_ffmpeg, find_ffprobe, probe
from ..pipeline import PipelineInput, PipelineResult, run_pipeline


APP_DISPLAY_NAME = "VuxGM Media"

QSS = """
QWidget {
    background: #0b1120;
    color: #e2e8f0;
    font-size: 13px;
}
QGroupBox {
    background: #111b2e;
    border: 1px solid #22314e;
    border-radius: 11px;
    margin-top: 14px;
    padding: 11px 13px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: #a78bfa;
    font-size: 12px;
}
QLineEdit, QComboBox, QPlainTextEdit {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px 8px;
}
QComboBox::drop-down { border: 0; }
QComboBox QAbstractItemView {
    background: #1e293b;
    selection-background-color: #2563eb;
}
QPushButton {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 12px;
}
QPushButton:hover { background: #273449; }
QPushButton#primary {
    background: #7c5cff;
    border: 0;
    font-weight: 700;
    padding: 10px 18px;
}
QPushButton#primary:hover { background: #6d4df5; }
QPushButton#accent {
    background: #1e293b;
    border: 1px solid #7c5cff;
    color: #c4b5fd;
    font-weight: 700;
    padding: 10px 12px;
}
QPushButton#accent:hover { background: #273449; }
QPushButton:checked {
    background: #2563eb;
    border: 0;
}
QCheckBox { spacing: 6px; }
QProgressBar {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    text-align: center;
    height: 18px;
}
QProgressBar::chunk {
    background: #22c55e;
    border-radius: 7px;
}
QPlainTextEdit {
    font-family: Consolas, monospace;
    font-size: 12px;
}
#sidebar {
    background: #0e1526;
    border-right: 1px solid #1e293b;
}
#sidebar QPushButton {
    text-align: left;
    padding: 9px 12px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}
#sidebar QPushButton:hover {
    background: #1b2740;
    border: 1px solid #334155;
}
#funcbar {
    background: #0b1120;
    border-bottom: 1px solid #1e293b;
}
#previewFrame {
    background: #070b14;
    border: 1px solid #26344f;
    border-radius: 9px;
}
"""


class StepBar(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        self.labels: list[QLabel] = []
        for text in ("1 Nguồn", "2 Nhận diện", "3 Dịch", "4 Giọng", "5 Render", "6 Xong"):
            label = QLabel(text)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                "background:#111b2e;border:1px solid #22314e;border-radius:7px;"
                "padding:5px 7px;color:#64748b;font-size:11px;font-weight:700;"
            )
            row.addWidget(label, 1)
            self.labels.append(label)

    def set_step(self, index: int) -> None:
        for i, label in enumerate(self.labels):
            if i < index:
                color = "#22c55e"
            elif i == index:
                color = "#c4b5fd"
            else:
                color = "#64748b"
            label.setStyleSheet(
                "background:#111b2e;border:1px solid #22314e;border-radius:7px;"
                f"padding:5px 7px;color:{color};font-size:11px;font-weight:700;"
            )


class PipelineWorker(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(str, int)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, settings: Settings, pipeline_input: PipelineInput, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.pipeline_input = pipeline_input
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            result = run_pipeline(
                self.settings,
                self.pipeline_input,
                log=self.log.emit,
                progress=self.progress.emit,
                should_stop=lambda: self._stop,
            )
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self._worker: Optional[PipelineWorker] = None

        self.setWindowTitle(f"{APP_DISPLAY_NAME} {APP_VERSION} — Dịch & lồng tiếng video")
        self.resize(1080, 760)
        self.setMinimumSize(980, 680)
        self.setStyleSheet(QSS)

        self._build()
        self._update_runtime_status()

    def _build(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._sidebar())

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self._function_switcher())

        self.stack = QStackedWidget()
        self.stack.addWidget(self._main_area())
        self.stack.addWidget(self._comic_page())
        right_layout.addWidget(self.stack, 1)

        root.addWidget(right, 1)

    def _function_switcher(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("funcbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 12, 14, 4)
        row.setSpacing(10)

        self.fn_video = QPushButton("🎬  Dịch & Lồng tiếng video")
        self.fn_comic = QPushButton("📖  Review Truyện Tranh")
        group = QButtonGroup(self)
        group.setExclusive(True)

        for button in (self.fn_video, self.fn_comic):
            button.setCheckable(True)
            button.setMinimumHeight(46)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton{font-size:14px;font-weight:700;border:1px solid #334155;"
                "border-radius:10px;padding:8px;color:#94a3b8;background:#1e293b;}"
                "QPushButton:hover{border-color:#7c3aed;}"
                "QPushButton:checked{background:#7c3aed;color:white;border-color:#7c3aed;}"
            )
            group.addButton(button)
            row.addWidget(button, 1)

        self.fn_video.setChecked(True)
        self.fn_video.clicked.connect(lambda: self._switch_function(0))
        self.fn_comic.clicked.connect(lambda: self._switch_function(1))
        return bar

    def _switch_function(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _side_head(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "color:#5b6b86;font-size:10px;font-weight:800;letter-spacing:1px;"
            "padding:3px 4px 0 4px;"
        )
        return label

    def _side_btn(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _sidebar(self) -> QWidget:
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(214)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 16, 14, 16)
        lay.setSpacing(7)

        icon_path = Path(__file__).resolve().parents[2] / "assets" / "vuxgm_icon.svg"
        logo = QLabel()
        if icon_path.exists():
            pixmap = QIcon(str(icon_path)).pixmap(92, 92)
            logo.setPixmap(pixmap)
            logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lay.addWidget(logo)

        title = QLabel("VuxGM Media")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title.setStyleSheet("font-size:20px;font-weight:800;color:#c4b5fd;")
        lay.addWidget(title)

        caption = QLabel("Dịch & lồng tiếng video")
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        caption.setStyleSheet("color:#64748b;font-size:11px;")
        lay.addWidget(caption)

        version = QLabel(f"Phiên bản {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        version.setStyleSheet("color:#a78bfa;font-size:10px;font-weight:700;padding-top:2px;")
        lay.addWidget(version)
        lay.addSpacing(12)

        lay.addWidget(self._side_head("NGUỒN"))
        lay.addWidget(self._side_btn("⬇   Tải video", lambda: self._not_ready("Tải video")))
        lay.addWidget(self._side_btn("🗂  Hàng chờ tải (qua đêm)", lambda: self._not_ready("Hàng chờ tải")))
        lay.addWidget(self._side_btn("📡  Quét kênh (tải hàng loạt)", lambda: self._not_ready("Quét kênh")))
        lay.addWidget(self._side_btn("📄  Chọn SRT", self._choose_srt))

        lay.addSpacing(10)
        lay.addWidget(self._side_head("CÔNG CỤ"))
        lay.addWidget(self._side_btn("🗂  Hàng chờ dịch (0)", lambda: self._not_ready("Hàng chờ dịch")))
        lay.addWidget(self._side_btn("✂  Ghép / Tách video", lambda: self._not_ready("Ghép / Tách video")))
        lay.addWidget(self._side_btn("⚡  Tăng tốc GPU", lambda: self._not_ready("Tăng tốc GPU")))
        lay.addWidget(self._side_btn("🔥  Giọng clone (tải gói)", lambda: self._not_ready("Giọng clone")))
        lay.addWidget(self._side_btn("🗣  Giọng Việt offline (tải gói)", lambda: self._not_ready("Giọng Việt offline")))
        lay.addWidget(self._side_btn("🔑  API Keys", lambda: self._not_ready("API Keys")))
        lay.addWidget(self._side_btn("🪪  Bản quyền / Nhập key", self._show_license_hint))
        lay.addWidget(self._side_btn("📜  Nhật ký làm video", lambda: self._not_ready("Nhật ký làm video")))
        lay.addStretch(1)

        self.engine_side = QLabel("● Engine sẵn sàng")
        self.engine_side.setStyleSheet("color:#22c55e;font-size:11px;")
        lay.addWidget(self.engine_side)
        return side

    def _main_area(self) -> QWidget:
        main = QWidget()
        lay = QVBoxLayout(main)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(10)

        top = QHBoxLayout()
        choose = QPushButton("📂 Chọn video")
        choose.clicked.connect(self._choose_video)
        top.addWidget(choose)

        self.video_edit = QLineEdit()
        self.video_edit.setPlaceholderText("Chưa chọn video — bấm 'Chọn video' hoặc 'Tải video' (thanh trái)")
        top.addWidget(self.video_edit, 1)

        clear_btn = QPushButton("✕")
        clear_btn.setFixedWidth(34)
        clear_btn.clicked.connect(self._clear_video)
        top.addWidget(clear_btn)

        self.preview_dur = QComboBox()
        for label, secs in (("30 giây", 30), ("1 phút", 60), ("2 phút", 120), ("Cả clip", 0)):
            self.preview_dur.addItem(label, secs)
        top.addWidget(self.preview_dur)

        preview_btn = QPushButton("👁 Xem trước")
        preview_btn.setObjectName("accent")
        preview_btn.clicked.connect(lambda: self._run_pipeline(preview=True))
        top.addWidget(preview_btn)

        self.run_btn = QPushButton("▶  Bắt đầu dịch")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(lambda: self._run_pipeline(preview=False))
        top.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹ Dừng")
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._stop_pipeline)
        top.addWidget(self.stop_btn)

        queue_btn = QPushButton("➕ Hàng chờ")
        queue_btn.clicked.connect(lambda: self._not_ready("Hàng chờ dịch"))
        top.addWidget(queue_btn)

        many_btn = QPushButton("➕📁 Nhiều video")
        many_btn.clicked.connect(lambda: self._not_ready("Thêm nhiều video"))
        top.addWidget(many_btn)

        lay.addLayout(top)

        self.stepbar = StepBar()
        lay.addWidget(self.stepbar)

        cols = QHBoxLayout()
        cols.setSpacing(10)

        cols.addWidget(self._right_panel(), 3)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(390)
        scroll.setWidget(self._left_panel())
        cols.addWidget(scroll, 2)

        lay.addLayout(cols, 1)

        self.status = QLabel("● Engine sẵn sàng")
        self.status.setStyleSheet("color:#22c55e;")
        lay.addWidget(self.status)
        return main

    def _left_panel(self) -> QWidget:
        panel = QWidget()
        root = QVBoxLayout(panel)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(9)

        mode_box = QGroupBox("CHẾ ĐỘ")
        mode_layout = QVBoxLayout(mode_box)
        mode_row = QHBoxLayout()
        self.mode_sub = QPushButton("🎬 Có phụ đề gốc → Dịch lại")
        self.mode_script = QPushButton("✍ Không phụ đề → Tự viết kịch bản")
        for button in (self.mode_sub, self.mode_script):
            button.setCheckable(True)
            mode_row.addWidget(button, 1)
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        mode_group.addButton(self.mode_sub)
        mode_group.addButton(self.mode_script)
        self.mode_sub.setChecked(True)
        self.mode_script.clicked.connect(lambda: self._not_ready("Tự viết kịch bản"))
        mode_layout.addLayout(mode_row)
        root.addWidget(mode_box)

        source_box = QGroupBox("NGUỒN PHỤ ĐỀ / LỜI THOẠI")
        source_layout = QVBoxLayout(source_box)

        self.source_combo = QComboBox()
        for label, code in (
            ("Phụ đề cứng trong video (OCR) — chuẩn, chậm", "hardsub"),
            ("🎧 Nghe thoại nhanh (giữ tên chuẩn)", "asr_fast"),
            ("Nghe audio (Whisper ASR)", "asr"),
            ("File SRT có sẵn", "srt"),
            ("Tự động", "auto"),
        ):
            self.source_combo.addItem(label, code)
        self.source_combo.setCurrentIndex(2)
        source_layout.addWidget(self.source_combo)

        self.srt_edit = QLineEdit()
        self.srt_edit.setPlaceholderText("File SRT có sẵn (nếu dùng)")
        source_layout.addWidget(self.srt_edit)

        srt_btn = QPushButton("📄 Chọn file SRT")
        srt_btn.clicked.connect(self._choose_srt)
        source_layout.addWidget(srt_btn)

        self.asr_check = QCheckBox("Dùng Whisper nếu không có SRT")
        self.asr_check.setChecked(True)
        source_layout.addWidget(self.asr_check)

        self.merge_check = QCheckBox("Gộp câu quá ngắn")
        self.merge_check.setChecked(True)
        source_layout.addWidget(self.merge_check)

        root.addWidget(source_box)

        ai_box = QGroupBox("DỊCH AI")
        ai_layout = QVBoxLayout(ai_box)
        self.translate_check = QCheckBox("Dịch sang tiếng Việt")
        self.translate_check.setEnabled(False)
        ai_layout.addWidget(self.translate_check)
        ai_note = QLabel("Phần dịch cloud/local đang được đưa lại vào mã nguồn mới.")
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet("color:#64748b;font-size:11px;")
        ai_layout.addWidget(ai_note)
        root.addWidget(ai_box)

        voice_box = QGroupBox("GIỌNG / LỒNG TIẾNG")
        voice_layout = QVBoxLayout(voice_box)
        self.tts_check = QCheckBox("Lồng tiếng TTS")
        self.tts_check.setEnabled(False)
        voice_layout.addWidget(self.tts_check)
        voice_note = QLabel("TTS / VieNeu / giọng clone đang được phục dựng từ cấu trúc bản cũ.")
        voice_note.setWordWrap(True)
        voice_note.setStyleSheet("color:#64748b;font-size:11px;")
        voice_layout.addWidget(voice_note)
        root.addWidget(voice_box)

        output_box = QGroupBox("PHỤ ĐỀ & RENDER")
        output_layout = QVBoxLayout(output_box)

        self.subtitle_check = QCheckBox("Tạo phụ đề / burn ASS")
        self.subtitle_check.setChecked(True)
        output_layout.addWidget(self.subtitle_check)

        self.render_check = QCheckBox("Render video")
        self.render_check.setChecked(True)
        output_layout.addWidget(self.render_check)

        self.srt_only_check = QCheckBox("Chỉ xuất phụ đề")
        self.srt_only_check.toggled.connect(self._sync_options)
        output_layout.addWidget(self.srt_only_check)

        root.addWidget(output_box)
        root.addStretch(1)
        return panel

    def _right_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)

        preview = QGroupBox("Xem trước")
        pv = QVBoxLayout(preview)
        self.preview_label = QLabel("Chọn video để xem thông tin / chuẩn bị xử lý")
        self.preview_label.setObjectName("previewFrame")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(245)
        self.preview_label.setWordWrap(True)
        pv.addWidget(self.preview_label)
        lay.addWidget(preview, 2)

        out_box = QGroupBox("Đầu ra")
        out_layout = QVBoxLayout(out_box)
        out_row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Đường dẫn video đầu ra")
        out_row.addWidget(self.output_edit, 1)
        out_btn = QPushButton("📁 Chọn nơi lưu")
        out_btn.clicked.connect(self._choose_output)
        out_row.addWidget(out_btn)
        out_layout.addLayout(out_row)

        self.runtime_label = QLabel()
        self.runtime_label.setWordWrap(True)
        self.runtime_label.setStyleSheet("color:#64748b;font-size:11px;")
        out_layout.addWidget(self.runtime_label)
        lay.addWidget(out_box)

        progress_box = QGroupBox("Tiến độ")
        progress_layout = QVBoxLayout(progress_box)
        self.stage_label = QLabel("Sẵn sàng")
        progress_layout.addWidget(self.stage_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        progress_layout.addWidget(self.progress)
        lay.addWidget(progress_box)

        log_box = QGroupBox("Nhật ký xử lý")
        log_layout = QVBoxLayout(log_box)
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Log xử lý sẽ hiện ở đây…")
        log_layout.addWidget(self.log_box)
        lay.addWidget(log_box, 2)
        return panel

    def _comic_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(24, 24, 24, 24)
        title = QLabel("📖 Review Truyện Tranh")
        title.setStyleSheet("font-size:22px;font-weight:800;color:#c4b5fd;")
        root.addWidget(title)

        card = QGroupBox("Review Truyện Tranh")
        layout = QVBoxLayout(card)
        note = QLabel(
            "Khung chức năng này thuộc giao diện bản cũ. "
            "Module ComicPanel đang được phục dựng riêng để đưa trở lại đầy đủ."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        root.addWidget(card)
        root.addStretch(1)
        return page

    def _not_ready(self, name: str) -> None:
        QMessageBox.information(
            self,
            APP_DISPLAY_NAME,
            f"{name} thuộc bản giao diện cũ và đang được đưa lại vào source VuxGM Media.",
        )

    def _show_license_hint(self) -> None:
        QMessageBox.information(
            self,
            "Bản quyền VuxGM Media",
            "License hiện dùng máy chủ vuxgm.site. "
            "Trạng thái key và nút Đăng xuất key nằm ở thanh trạng thái phía dưới.",
        )

    def _clear_video(self) -> None:
        self.video_edit.clear()
        self.preview_label.setText("Chọn video để xem thông tin / chuẩn bị xử lý")

    def _update_runtime_status(self) -> None:
        self.runtime_label.setText(f"FFmpeg: {find_ffmpeg()}   |   FFprobe: {find_ffprobe()}")

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn video",
            "",
            "Video (*.mp4 *.mkv *.mov *.avi *.webm *.m4v);;Tất cả (*.*)",
        )
        if not path:
            return
        self.video_edit.setText(path)
        if not self.output_edit.text().strip():
            p = Path(path)
            self.output_edit.setText(str(p.with_name(f"{p.stem}_vuxgm_media.mp4")))
        self._inspect_video()

    def _choose_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn SRT", "", "SubRip (*.srt);;Tất cả (*.*)")
        if path:
            self.srt_edit.setText(path)
            idx = self.source_combo.findData("srt")
            if idx >= 0:
                self.source_combo.setCurrentIndex(idx)

    def _choose_output(self) -> None:
        suggested = self.output_edit.text().strip() or "output_vuxgm_media.mp4"
        path, _ = QFileDialog.getSaveFileName(self, "Lưu video", suggested, "MP4 (*.mp4);;MKV (*.mkv)")
        if path:
            self.output_edit.setText(path)

    def _inspect_video(self) -> None:
        path = self.video_edit.text().strip()
        if not path:
            return
        try:
            info = probe(path)
            self.preview_label.setText(
                f"{Path(path).name}\n\n"
                f"{info.width} × {info.height}\n"
                f"{info.duration_ms / 1000:.2f} giây\n"
                f"Audio: {'Có' if info.has_audio else 'Không'}\n"
                f"Rotation: {info.rotation}"
            )
            self._append_log(
                f"Video: {info.width}x{info.height}, {info.duration_ms / 1000:.2f}s, "
                f"rotation={info.rotation}, audio={'có' if info.has_audio else 'không'}"
            )
        except Exception as exc:
            self.preview_label.setText(f"Không đọc được thông tin video:\n{exc}")

    def _sync_options(self, checked: bool) -> None:
        if checked:
            self.render_check.setChecked(False)
            self.render_check.setEnabled(False)
        else:
            self.render_check.setEnabled(True)

    def _build_input(self, *, preview: bool) -> PipelineInput:
        srt_only = self.srt_only_check.isChecked()
        srt_path = self.srt_edit.text().strip()
        do_subtitle = self.subtitle_check.isChecked()
        if not srt_path and not self.asr_check.isChecked():
            do_subtitle = False

        preview_seconds = int(self.preview_dur.currentData() or 0) if preview else 0

        return PipelineInput(
            video_path=self.video_edit.text().strip() or None,
            srt_path=srt_path or None,
            output_path=self.output_edit.text().strip() or None,
            source="srt" if srt_path else "asr",
            voice=None,
            do_subtitle=do_subtitle,
            do_translate=False,
            do_review=False,
            do_tts=False,
            do_render=self.render_check.isChecked() and not srt_only,
            merge_short=self.merge_check.isChecked(),
            preview_seconds=preview_seconds,
            export_srt_only=srt_only,
        )

    def _run_pipeline(self, *, preview: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            return

        selected_source = str(self.source_combo.currentData() or "")
        if selected_source in {"hardsub", "asr_fast"} and not self.srt_edit.text().strip():
            QMessageBox.information(
                self,
                "Chức năng đang phục dựng",
                "OCR hardsub / nghe thoại nhanh chưa được nối lại trong pipeline mới. "
                "Hiện có thể dùng Whisper ASR hoặc file SRT.",
            )
            return

        inp = self._build_input(preview=preview)
        if not inp.srt_path and inp.do_subtitle and not inp.video_path:
            QMessageBox.information(self, "Thiếu video", "Whisper ASR cần video hoặc file âm thanh đầu vào.")
            return
        if inp.export_srt_only and not inp.srt_path and not inp.video_path:
            QMessageBox.information(self, "Thiếu đầu vào", "Hãy chọn video hoặc một file SRT.")
            return
        if inp.do_render and not inp.video_path:
            QMessageBox.information(self, "Thiếu video", "Render video cần một file video đầu vào.")
            return

        self.log_box.clear()
        self.progress.setValue(0)
        self.stage_label.setText("Khởi động…")
        self.stepbar.set_step(0)
        self.run_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)

        worker = PipelineWorker(self.settings, inp, self)
        worker.log.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._thread_finished)
        self._worker = worker
        worker.start()

    def _stop_pipeline(self) -> None:
        if self._worker is not None:
            self._worker.request_stop()
            self.stop_btn.setEnabled(False)
            self.stage_label.setText("Đang dừng…")
            self._append_log("Yêu cầu dừng đã được gửi.")

    @pyqtSlot(str)
    def _append_log(self, text: str) -> None:
        self.log_box.appendPlainText(text)

    @pyqtSlot(str, int)
    def _on_progress(self, stage: str, value: int) -> None:
        self.stage_label.setText(stage)
        self.progress.setValue(value)
        lower = stage.lower()
        if "asr" in lower or "nhận" in lower or "whisper" in lower:
            self.stepbar.set_step(1)
        elif "dịch" in lower or "translate" in lower:
            self.stepbar.set_step(2)
        elif "tts" in lower or "giọng" in lower:
            self.stepbar.set_step(3)
        elif "render" in lower or "ffmpeg" in lower:
            self.stepbar.set_step(4)

    @pyqtSlot(object)
    def _on_done(self, result: PipelineResult) -> None:
        self.progress.setValue(100)
        self.stage_label.setText("Hoàn tất")
        self.stepbar.set_step(5)
        if result.detected_language:
            self._append_log(f"Ngôn ngữ ASR: {result.detected_language}")
        outputs = [v for v in (result.srt_out, result.ass_out, result.audio_out, result.video_out) if v]
        if outputs:
            self._append_log("Đầu ra:\n" + "\n".join(outputs))
        QMessageBox.information(
            self,
            "Hoàn tất",
            "Xử lý xong." + ("\n\n" + "\n".join(outputs) if outputs else ""),
        )

    @pyqtSlot(str)
    def _on_failed(self, message: str) -> None:
        self.stage_label.setText("Lỗi")
        self._append_log(message)
        QMessageBox.critical(self, "Xử lý thất bại", message.split("\n", 1)[0])

    @pyqtSlot()
    def _thread_finished(self) -> None:
        self._worker = None
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setVisible(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker is not None and self._worker.isRunning():
            self._worker.request_stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
