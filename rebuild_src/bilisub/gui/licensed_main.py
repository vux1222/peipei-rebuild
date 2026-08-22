from __future__ import annotations

import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from ..license_client import LicenseClient, LicenseError
from .license_dialog import LicenseController, LicenseDialog
from .main_window import MainWindow


def _request_license(client: LicenseClient, parent=None) -> bool:
    dialog = LicenseDialog(client, parent)
    return bool(dialog.exec())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("VuxGM")

    client = LicenseClient()
    try:
        state = client.startup()
    except LicenseError as exc:
        state = None
        QMessageBox.warning(None, "VuxGM License", str(exc))

    if state is None and not _request_license(client):
        return 0

    window = MainWindow()
    status = window.statusBar()
    license_label = QLabel(client.status_text())
    status.addPermanentWidget(license_label, 1)

    update_btn = QPushButton("Tải bản mới")
    update_btn.setToolTip("Mở API tải file EXE mới nhất từ vuxgm.site")
    update_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(client.latest_download_url())))
    status.addPermanentWidget(update_btn)

    logout_btn = QPushButton("Đăng xuất key")
    status.addPermanentWidget(logout_btn)

    controller = LicenseController(client, window)
    controller.status_changed.connect(license_label.setText)

    def require_reactivation(message: str) -> None:
        controller.stop()
        window.setEnabled(False)
        QMessageBox.warning(window, "License không còn hợp lệ", message)
        if _request_license(client, window):
            license_label.setText(client.status_text())
            window.setEnabled(True)
            controller.start()
        else:
            app.quit()

    controller.invalidated.connect(require_reactivation)

    def logout() -> None:
        answer = QMessageBox.question(
            window,
            "Đăng xuất license",
            "Giải phóng key khỏi máy này để có thể kích hoạt trên máy khác?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        logout_btn.setEnabled(False)
        try:
            if not client.logout():
                QMessageBox.warning(window, "Đăng xuất", "Server chưa xác nhận released=true nên app chưa xóa key local.")
                return
            controller.stop()
            window.setEnabled(False)
            if _request_license(client, window):
                license_label.setText(client.status_text())
                window.setEnabled(True)
                controller.start()
            else:
                app.quit()
        except LicenseError as exc:
            QMessageBox.warning(window, "Không đăng xuất được", str(exc))
        finally:
            logout_btn.setEnabled(True)

    logout_btn.clicked.connect(logout)
    controller.start()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
