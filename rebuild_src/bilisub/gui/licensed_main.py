from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices, QIcon
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from ..license_bootstrap import get_license_public_key
from ..license_client import LicenseClient, LicenseError
from .license_dialog import LicenseController, LicenseDialog
from .main_window import APP_DISPLAY_NAME, MainWindow


def _asset_path(name: str) -> Path:
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "assets" / name)
    candidates.append(Path(__file__).resolve().parents[2] / "assets" / name)
    candidates.append(Path(sys.executable).resolve().parent / "assets" / name)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if candidates else Path(name)


def _request_license(client: LicenseClient, parent=None) -> bool:
    dialog = LicenseDialog(client, parent)
    return bool(dialog.exec())


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("VuxGM")
    app.setOrganizationDomain("vuxgm.site")

    icon_path = _asset_path("vuxgm_icon.svg")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    try:
        public_key = get_license_public_key()
        client = LicenseClient(public_key_b64=public_key)
    except LicenseError as exc:
        QMessageBox.critical(
            None,
            f"{APP_DISPLAY_NAME} License",
            f"Không khởi tạo được kết nối license VuxGM.\n\n{exc}",
        )
        return 1

    try:
        state = client.startup()
    except LicenseError as exc:
        state = None
        QMessageBox.warning(None, f"{APP_DISPLAY_NAME} License", str(exc))

    if state is None and not _request_license(client):
        return 0

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    status = window.statusBar()
    license_label = QLabel(client.status_text())
    status.addPermanentWidget(license_label, 1)

    update_btn = QPushButton("Tải bản mới")
    update_btn.setToolTip("Tải bản VuxGM Media mới nhất từ vuxgm.site")
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
