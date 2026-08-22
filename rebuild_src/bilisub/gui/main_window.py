from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_SITE_URL, APP_VERSION, Settings
from ..ffmpeg_utils import find_ffmpeg, find_ffprobe, probe
from ..pipeline import PipelineInput, PipelineResult, run_pipeline


class PipelineWorker(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(str, int)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, settings: Settings, pipeline_input: PipelineInput) -> None:
        super().__init__()
        self.settings = settings
        self.pipeline_input = pipeline_input
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @pyqtSlot()
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
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self._thread: Optional[QThread] = None
        self._worker: Optional[PipelineWorker] = None

        self.setWindowTitle(f"PeiPei Rebuild {APP_VERSION}")
        self.resize(900, 680)
        self._build_ui()
        self._update_runtime_status()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)

        title_row = QHBoxLayout()
        title = QLabel(f"<b>PeiPei Rebuild</b> <span style='color:#777'>{APP_VERSION}</span>")
        title_row.addWidget(title)
        title_row.addStretch(1)
        site_button = QPushButton(APP_SITE_URL)
        site_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(APP_SITE_URL)))
        title_row.addWidget(site_button)
        root.addLayout(title_row)

        note = QLabel(
            "Bản phục dựng hiện chạy được nhập SRT → làm sạch/gộp → xuất SRT/ASS → render FFmpeg. "
            "ASR/OCR, dịch AI và TTS sẽ được nối vào sau khi các module tương ứng được phục dựng."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        form = QFormLayout()

        self.video_edit = QLineEdit()
        video_row = QHBoxLayout()
        video_row.addWidget(self.video_edit, 1)
        video_btn = QPushButton("Chọn video…")
        video_btn.clicked.connect(self._choose_video)
        video_row.addWidget(video_btn)
        form.addRow("Video", video_row)

        self.srt_edit = QLineEdit()
        srt_row = QHBoxLayout()
        srt_row.addWidget(self.srt_edit, 1)
        srt_btn = QPushButton("Chọn SRT…")
        srt_btn.clicked.connect(self._choose_srt)
        srt_row.addWidget(srt_btn)
        form.addRow("Phụ đề SRT", srt_row)

        self.output_edit = QLineEdit()
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit, 1)
        output_btn = QPushButton("Lưu video…")
        output_btn.clicked.connect(self._choose_output)
        output_row.addWidget(output_btn)
        form.addRow("Video đầu ra", output_row)

        self.preview_spin = QSpinBox()
        self.preview_spin.setRange(0, 3600)
        self.preview_spin.setSuffix(" giây (0 = toàn bộ)")
        form.addRow("Preview", self.preview_spin)

        root.addLayout(form)

        option_row = QHBoxLayout()
        self.subtitle_check = QCheckBox("Tạo phụ đề / burn ASS")
        self.subtitle_check.setChecked(True)
        option_row.addWidget(self.subtitle_check)

        self.merge_check = QCheckBox("Gộp câu quá ngắn")
        self.merge_check.setChecked(True)
        option_row.addWidget(self.merge_check)

        self.render_check = QCheckBox("Render video")
        self.render_check.setChecked(True)
        option_row.addWidget(self.render_check)

        self.srt_only_check = QCheckBox("Chỉ xuất phụ đề")
        option_row.addWidget(self.srt_only_check)
        root.addLayout(option_row)

        pending_row = QHBoxLayout()
        self.translate_check = QCheckBox("Dịch AI (đang phục dựng)")
        self.translate_check.setChecked(False)
        self.translate_check.setEnabled(False)
        pending_row.addWidget(self.translate_check)

        self.tts_check = QCheckBox("Tạo giọng TTS (đang phục dựng)")
        self.tts_check.setChecked(False)
        self.tts_check.setEnabled(False)
        pending_row.addWidget(self.tts_check)

        self.asr_check = QCheckBox("ASR/OCR nếu không có SRT (đang phục dựng)")
        self.asr_check.setChecked(False)
        self.asr_check.setEnabled(False)
        pending_row.addWidget(self.asr_check)
        root.addLayout(pending_row)

        self.runtime_label = QLabel()
        self.runtime_label.setWordWrap(True)
        root.addWidget(self.runtime_label)

        button_row = QHBoxLayout()
        self.inspect_btn = QPushButton("Kiểm tra video")
        self.inspect_btn.clicked.connect(self._inspect_video)
        button_row.addWidget(self.inspect_btn)

        self.run_btn = QPushButton("Chạy")
        self.run_btn.clicked.connect(self._run_pipeline)
        button_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("Dừng")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_pipeline)
        button_row.addWidget(self.stop_btn)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.stage_label = QLabel("Sẵn sàng")
        root.addWidget(self.stage_label)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Log xử lý sẽ hiện ở đây…")
        root.addWidget(self.log_box, 1)

        self.setCentralWidget(central)

        self.srt_only_check.toggled.connect(self._sync_options)

    def _sync_options(self, checked: bool) -> None:
        if checked:
            self.render_check.setChecked(False)
            self.render_check.setEnabled(False)
        else:
            self.render_check.setEnabled(True)

    def _update_runtime_status(self) -> None:
        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()
        self.runtime_label.setText(f"FFmpeg: {ffmpeg}   |   FFprobe: {ffprobe}")

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
            self.output_edit.setText(str(p.with_name(f"{p.stem}_peipei_rebuild.mp4")))

    def _choose_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn SRT", "", "SubRip (*.srt);;Tất cả (*.*)")
        if path:
            self.srt_edit.setText(path)

    def _choose_output(self) -> None:
        suggested = self.output_edit.text().strip() or "output_peipei_rebuild.mp4"
        path, _ = QFileDialog.getSaveFileName(self, "Lưu video", suggested, "MP4 (*.mp4);;MKV (*.mkv)")
        if path:
            self.output_edit.setText(path)

    def _inspect_video(self) -> None:
        path = self.video_edit.text().strip()
        if not path:
            QMessageBox.information(self, "Thiếu video", "Hãy chọn video trước.")
            return
        try:
            info = probe(path)
            self._append_log(
                f"Video: {info.width}x{info.height}, {info.duration_ms / 1000:.2f}s, "
                f"rotation={info.rotation}, audio={'có' if info.has_audio else 'không'}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Không đọc được video", str(exc))

    def _build_input(self) -> PipelineInput:
        srt_only = self.srt_only_check.isChecked()
        return PipelineInput(
            video_path=self.video_edit.text().strip() or None,
            srt_path=self.srt_edit.text().strip() or None,
            output_path=self.output_edit.text().strip() or None,
            source="srt" if self.srt_edit.text().strip() else "auto",
            voice=None,
            do_subtitle=self.subtitle_check.isChecked(),
            do_translate=False,
            do_review=False,
            do_tts=False,
            do_render=self.render_check.isChecked() and not srt_only,
            merge_short=self.merge_check.isChecked(),
            preview_seconds=self.preview_spin.value(),
            export_srt_only=srt_only,
        )

    def _run_pipeline(self) -> None:
        if self._thread is not None:
            return

        inp = self._build_input()
        if not inp.srt_path:
            QMessageBox.information(
                self,
                "Cần SRT ở giai đoạn này",
                "ASR/OCR chưa được nối vào bản rebuild. Hãy chọn một file SRT để test pipeline hiện tại.",
            )
            return
        if inp.do_render and not inp.video_path:
            QMessageBox.information(self, "Thiếu video", "Render video cần một file video đầu vào.")
            return

        self.log_box.clear()
        self.progress.setValue(0)
        self.stage_label.setText("Khởi động…")
        self.run_btn.setEnabled(False)
        self.inspect_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        thread = QThread(self)
        worker = PipelineWorker(self.settings, inp)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self._append_log)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_done)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)

        self._thread = thread
        self._worker = worker
        thread.start()

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

    @pyqtSlot(object)
    def _on_done(self, result: PipelineResult) -> None:
        self.progress.setValue(100)
        self.stage_label.setText("Hoàn tất")
        outputs = [
            value
            for value in (result.srt_out, result.ass_out, result.audio_out, result.video_out)
            if value
        ]
        if outputs:
            self._append_log("Đầu ra:\n" + "\n".join(outputs))
        QMessageBox.information(self, "Hoàn tất", "Xử lý xong." + ("\n\n" + "\n".join(outputs) if outputs else ""))

    @pyqtSlot(str)
    def _on_failed(self, message: str) -> None:
        self.stage_label.setText("Lỗi")
        self._append_log(message)
        short = message.split("\n", 1)[0]
        QMessageBox.critical(self, "Xử lý thất bại", short)

    @pyqtSlot()
    def _thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self.run_btn.setEnabled(True)
        self.inspect_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker is not None:
            self._worker.request_stop()
        super().closeEvent(event)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("PeiPei Rebuild")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
