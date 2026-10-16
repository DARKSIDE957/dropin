#!/usr/bin/env python3
"""
Manual Browse tour for Dropin (real display when available).

Activates the Browse control via keyboard (Space), opens a non-native
QFileDialog (native KDE/portal dialogs cannot be driven reliably on Wayland),
selects a package with keyboard/programmatic selection, then watches the
inspect → confirmation UI for ~10 seconds. Monitors process liveness.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_INSTALLED = Path.home() / ".local" / "share" / "dropin" / "app"
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))

# Prefer real session display; fall back to offscreen only if needed.
if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

os.environ["DROPIN_E2E"] = "1"

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

PAUSE_SEC = 10
TARGET = Path.home() / "Applications" / "PlayDeck_Remix.AppImage"
if not TARGET.is_file():
    candidates = sorted((Path.home() / "Applications").glob("*.AppImage"))
    TARGET = candidates[0] if candidates else Path("/etc/hosts")


def linger(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.05)


def dismiss_modals(app: QApplication) -> None:
    for w in app.topLevelWidgets():
        if isinstance(w, QMessageBox) and w.isVisible():
            w.done(QMessageBox.StandardButton.Ok)
            w.close()


def main() -> int:
    print(f"Browse manual tour — target={TARGET}", flush=True)
    print(f"platform display DISPLAY={os.environ.get('DISPLAY')!r} "
          f"WAYLAND={os.environ.get('WAYLAND_DISPLAY')!r}", flush=True)

    if not TARGET.is_file():
        print(f"FAIL: no package file at {TARGET}", flush=True)
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    from dropin.ui.main_window import MainWindow
    from dropin.ui.drop_zone import DropZone

    window = MainWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    app.processEvents()
    time.sleep(0.5)

    # Replace Browse handler with a keyboard-drivable non-native dialog.
    zone: DropZone = window.drop_zone
    selected: list[str] = []

    def browse_with_qt_dialog():
        dlg = QFileDialog(window, "Select Application Package")
        dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dlg.setNameFilter(
            "Supported Packages (*.AppImage *.deb *.rpm *.flatpakref *.flatpak "
            "*.tar.gz *.tar.xz *.zip);;All Files (*)"
        )
        dlg.setDirectory(str(TARGET.parent))
        dlg.selectFile(TARGET.name)
        dlg.show()
        app.processEvents()
        print("  Browse dialog open (non-native Qt) — pausing 2s then Accept", flush=True)
        linger(app, 2.0)
        # Keyboard: focus Open/Accept and activate with Space/Enter.
        dlg.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(dlg, Qt.Key.Key_Return)
        app.processEvents()
        if dlg.result() != QFileDialog.DialogCode.Accepted:
            # Fallback programmatic accept of pre-selected file.
            paths = dlg.selectedFiles()
            if not paths:
                dlg.selectFile(str(TARGET))
                paths = [str(TARGET)]
            dlg.hide()
            if paths:
                selected.append(paths[0])
                zone.file_selected.emit(paths[0])
            print(f"  dialog fallback accept → {paths}", flush=True)
        else:
            paths = dlg.selectedFiles()
            if paths:
                selected.append(paths[0])
                zone.file_selected.emit(paths[0])
            print(f"  dialog accepted → {paths}", flush=True)
        dlg.close()

    zone.browse_btn.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    print("  Focusing Browse… Space to activate", flush=True)
    # Hook: run our dialog instead of native getOpenFileName.
    zone._on_browse_clicked = browse_with_qt_dialog  # type: ignore[method-assign]
    QTest.keyClick(zone.browse_btn, Qt.Key.Key_Space)
    app.processEvents()
    # If Space didn't fire (focus quirks), call directly after keyboard attempt.
    if not selected and window.stack.currentIndex() == 0:
        print("  Space did not complete flow — invoking Browse handler", flush=True)
        browse_with_qt_dialog()
        app.processEvents()

    # Wait for inspect → confirmation
    for _ in range(80):
        app.processEvents()
        time.sleep(0.1)
        dismiss_modals(app)
        if window.stack.currentIndex() == 1:
            break

    idx = window.stack.currentIndex()
    print(f"  stack index after Browse={idx}", flush=True)

    ok = True
    detail = ""
    if idx == 1:
        name = window.confirmation_view.name_label.text()
        fmt = window.confirmation_view.format_badge.text()
        size = window.confirmation_view.size_row[2].text()
        install_enabled = window.confirmation_view.install_btn.isEnabled()
        detail = f"confirm name={name!r} format={fmt!r} size={size!r} install_enabled={install_enabled}"
        print(f"  UI: {detail}", flush=True)
        print(f"  Watching confirmation for {PAUSE_SEC}s…", flush=True)
        linger(app, PAUSE_SEC)
        alive = window.isVisible()
        print(f"  after {PAUSE_SEC}s: window_visible={alive} stack={window.stack.currentIndex()}", flush=True)
        if not alive:
            ok = False
            detail += " | window died"
        # Cancel rather than install
        window.confirmation_view.cancel_btn.setFocus(Qt.FocusReason.TabFocusReason)
        QTest.keyClick(window.confirmation_view.cancel_btn, Qt.Key.Key_Space)
        app.processEvents()
        linger(app, 0.5)
    elif idx == 3:
        # Result/error page
        ok = False
        detail = "landed on result page instead of confirmation"
        print(f"  FAIL: {detail}", flush=True)
        linger(app, PAUSE_SEC)
    else:
        ok = False
        detail = f"unexpected stack={idx}; selected={selected}"
        print(f"  FAIL: {detail}", flush=True)
        linger(app, 2.0)

    window.close()
    app.processEvents()
    time.sleep(0.3)

    print("PASS" if ok else "FAIL", "—", detail, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
