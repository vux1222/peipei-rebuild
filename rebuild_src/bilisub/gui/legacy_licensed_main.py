from __future__ import annotations

import sys

from ..legacy_bridge import prepare_legacy_runtime


APP_DISPLAY_NAME = "VuxGM Media"
APP_VERSION = "1.0.0"


def _brand_text(text: str) -> str:
    return (
        str(text or "")
        .replace("PeiPei Dub", APP_DISPLAY_NAME)
        .replace("PeiPeiReup", APP_DISPLAY_NAME)
        .replace("PeiPei Reup", APP_DISPLAY_NAME)
        .replace("PeiPei", "VuxGM")
    )


def _rebrand_static_widgets(window) -> None:
    from PyQt6.QtWidgets import QCheckBox, QGroupBox, QLabel, QPushButton

    window.setWindowTitle(f"{APP_DISPLAY_NAME} {APP_VERSION} — Dịch & lồng tiếng video")
    for cls in (QLabel, QPushButton, QCheckBox, QGroupBox):
        for widget in window.findChildren(cls):
            try:
                old = widget.text() if hasattr(widget, "text") else widget.title()
                new = _brand_text(old)
                if new != old:
                    if hasattr(widget, "setText"):
                        widget.setText(new)
                    elif hasattr(widget, "setTitle"):
                        widget.setTitle(new)
            except Exception:
                pass
            try:
                tip = widget.toolTip()
                if tip:
                    widget.setToolTip(_brand_text(tip))
            except Exception:
                pass


def _disable_old_credit_ui(window) -> None:
    settings = getattr(window, "settings", None)
    if settings is not None and hasattr(settings, "ai_credit_mode"):
        try:
            settings.ai_credit_mode = False
        except Exception:
            pass

    for name in ("_credit_bar", "credit_lbl", "credit_topup_btn"):
        widget = getattr(window, name, None)
        if widget is not None:
            try:
                widget.setVisible(False)
            except Exception:
                pass


def main() -> int:
    # First make the extracted _internal runtime available. This allows the app
    # to reuse its original PyQt/native packages even on a clean Python install.
    try:
        paths, legacy_main = prepare_legacy_runtime()
    except Exception as exc:
        # PyQt may not be importable if runtime preparation itself failed, so use
        # a console message as a guaranteed fallback.
        print(f"{APP_DISPLAY_NAME}: không nạp được legacy runtime: {exc}", file=sys.stderr)
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                f"{APP_DISPLAY_NAME} — lỗi runtime cũ",
                "Không nạp được bộ chức năng gốc từ legacy_app.\n\n" + str(exc),
            )
        except Exception:
            pass
        return 1

    from PyQt6.QtCore import QTimer
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setOrganizationName("VuxGM")
    app.setOrganizationDomain("vuxgm.site")

    from ..license_client import LicenseError as SourceLicenseError
    from ..vuxgm_license import get_client
    from .license_dialog import LicenseController, LicenseDialog

    icon_path = paths.repo_root / "rebuild_src" / "assets" / "vuxgm_icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    client = get_client()
    try:
        state = client.startup()
    except SourceLicenseError as exc:
        state = None
        if not exc.network:
            QMessageBox.warning(None, f"{APP_DISPLAY_NAME} License", str(exc))

    if state is None:
        dialog = LicenseDialog(client)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return 0

    try:
        window = legacy_main.MainWindow()
    except Exception as exc:
        QMessageBox.critical(
            None,
            f"{APP_DISPLAY_NAME} — lỗi mở giao diện gốc",
            "Đã qua bước license nhưng không dựng được MainWindow legacy.\n\n" + repr(exc),
        )
        return 1

    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    _rebrand_static_widgets(window)
    _disable_old_credit_ui(window)

    controller = LicenseController(client, window)

    def invalidated(message: str) -> None:
        controller.stop()
        window.setEnabled(False)
        QMessageBox.warning(window, "License không còn hợp lệ", message)
        dialog = LicenseDialog(client, window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            window.setEnabled(True)
            controller.start()
        else:
            app.quit()

    controller.invalidated.connect(invalidated)
    controller.start()

    QTimer.singleShot(0, lambda: _rebrand_static_widgets(window))
    QTimer.singleShot(500, lambda: _disable_old_credit_ui(window))

    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
