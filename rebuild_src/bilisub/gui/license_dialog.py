from __future__ import annotations

import threading

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from ..config import APP_SITE_URL
from ..license_client import HEARTBEAT_SECONDS, LicenseClient, LicenseError


APP_DISPLAY_NAME = "VuxGM Media"


class LicenseDialog(QDialog):
    def __init__(self, client: LicenseClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self.setWindowTitle(f"Kích hoạt {APP_DISPLAY_NAME}")
        self.setModal(True)
        self.setMinimumWidth(470)

        root = QVBoxLayout(self)
        title = QLabel(f"<b>{APP_DISPLAY_NAME} License</b>")
        title.setStyleSheet("font-size:20px")
        root.addWidget(title)

        note = QLabel(
            "Nhập license key để kích hoạt app trên máy này. "
            "App sẽ xác minh chữ ký Ed25519 trước khi lưu license."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("VUX-XXXX-XXXX-XXXX-XXXX")
        self.key_edit.returnPressed.connect(self._activate)
        root.addWidget(self.key_edit)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.activate_btn = QPushButton("Kích hoạt")
        self.activate_btn.clicked.connect(self._activate)
        buttons.addWidget(self.activate_btn)

        buy_btn = QPushButton("Mua / quản lý key")
        buy_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(APP_SITE_URL)))
        buttons.addWidget(buy_btn)

        cancel_btn = QPushButton("Thoát")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _activate(self) -> None:
        key = self.key_edit.text().strip().upper()
        self.activate_btn.setEnabled(False)
        self.status.setText(f"Đang kết nối máy chủ {APP_DISPLAY_NAME}…")
        try:
            state = self.client.activate(key)
            self.status.setText(f"Kích hoạt thành công. Hết hạn: {state.expires_at}")
            self.accept()
        except LicenseError as exc:
            self.status.setText(str(exc))
            QMessageBox.warning(self, "Kích hoạt thất bại", str(exc))
        finally:
            self.activate_btn.setEnabled(True)


class LicenseController(QObject):
    status_changed = pyqtSignal(str)
    invalidated = pyqtSignal(str)

    def __init__(self, client: LicenseClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(HEARTBEAT_SECONDS * 1000)
        self._timer.timeout.connect(self._start_heartbeat)

    def start(self) -> None:
        self._timer.start()
        self.status_changed.emit(self.client.status_text())

    def stop(self) -> None:
        self._timer.stop()

    def _start_heartbeat(self) -> None:
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._heartbeat_worker, name="VuxGMMediaLicenseHeartbeat", daemon=True).start()

    def _heartbeat_worker(self) -> None:
        try:
            self.client.heartbeat()
            self.status_changed.emit(self.client.status_text())
        except LicenseError as exc:
            if exc.status_code in {400, 403, 404, 409}:
                self.client.clear_local()
                self.invalidated.emit(str(exc))
            elif exc.network:
                self.status_changed.emit(self.client.status_text() + " · mất kết nối heartbeat")
            else:
                self.status_changed.emit(str(exc))
        finally:
            self._busy = False
