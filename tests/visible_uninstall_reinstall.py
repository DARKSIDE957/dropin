#!/usr/bin/env python3
"""Visible uninstall → reinstall; verifies the redesign progress page paints."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_INSTALLED = Path.home() / ".local" / "share" / "dropin" / "app"
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))

os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.pop("DROPIN_E2E", None)

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtWidgets import QApplication, QMessageBox

APP_ID = "dropin-appimage-playdeck_remix"
STEP_PAUSE = 10
INSTALL_MIN_WATCH = 35
REDISCOVER_CANDIDATES = [
    Path.home() / "Applications" / "PlayDeck-4.0.0-remix.AppImage",
    Path.home() / "Applications" / "PlayDeck_Remix.AppImage",
]


def say(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
    try:
        import subprocess
        subprocess.run(
            ["notify-send", "-a", "Dropin tour", "Dropin", msg[:180]],
            check=False,
            timeout=2,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def ensure_visible(window, app: QApplication) -> None:
    if window is None:
        return
    from dropin.ui.animations import fade_widget
    from PySide6.QtWidgets import QWidget

    fade_widget(window)
    for w in window.findChildren(QWidget):
        if w.graphicsEffect() is not None:
            fade_widget(w)
    window.setWindowState(
        (window.windowState() & ~Qt.WindowState.WindowMinimized)
        | Qt.WindowState.WindowActive
    )
    screen = app.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        frame = window.frameGeometry()
        frame.moveCenter(geo.center())
        window.move(frame.topLeft())
    window.show()
    window.showNormal()
    window.raise_()
    window.activateWindow()
    app.processEvents()


def linger(app, window, seconds: float, why: str = "") -> None:
    if why:
        say(f"… waiting {seconds:.0f}s — {why}")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ensure_visible(window, app)
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.1)


def _click_yes(app, timeout_s=8.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        for w in app.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                btn = w.button(QMessageBox.StandardButton.Yes)
                if btn:
                    say("Uninstall confirm — Yes")
                    btn.click()
                    return True
        time.sleep(0.05)
    return False


def _dismiss_ok(app, timeout_s=8.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        for w in app.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                say(f"Info — OK ({w.text()[:60]!r})")
                ok = w.button(QMessageBox.StandardButton.Ok)
                (ok.click() if ok else w.accept())
                return
        time.sleep(0.05)


def main() -> int:
    say("Visible tour — redesigned progress page (name/version/% visible)")
    if not any(p.is_file() for p in REDISCOVER_CANDIDATES):
        say("FAIL: no PlayDeck source AppImage")
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    from dropin.ui.main_window import MainWindow
    from dropin.ui.installed_dialog import InstalledAppsDialog
    from dropin.ui.pick_file_dialog import PickInstallFileDialog
    from dropin.ui.theme import apply_system_theme
    from dropin.core.registry import get_registry

    window = MainWindow()
    ensure_visible(window, app)
    say("Window UP — landing should show drop zone")
    linger(app, window, STEP_PAUSE, "landing")

    say("Opening Installed apps")
    dlg = InstalledAppsDialog(window)
    apply_system_theme(dlg)
    dlg.show()
    ensure_visible(dlg, app)
    linger(app, dlg, STEP_PAUSE, "installed list")

    registry = get_registry()
    say(f"Before: { {a.id: a.name for a in registry.list_apps()} }")
    target = registry.get_app(APP_ID)
    if target is None:
        for a in registry.list_apps():
            if "playdeck" in a.name.lower() and "remix" in a.name.lower():
                target = a
                break

    if target:
        say(f"Uninstall {target.name}")
        QTimer.singleShot(2000, lambda: _click_yes(app))
        QTimer.singleShot(4500, lambda: _dismiss_ok(app))
        dlg._confirm_uninstall(target)
        app.processEvents()
        linger(app, dlg, STEP_PAUSE, "after uninstall")
        dlg.load_apps()
        names = [a.name for a in registry.list_apps()]
        gone = APP_ID not in {a.id for a in registry.list_apps()}
        say(f"After uninstall: {names} | gone={gone}")
        linger(app, dlg, STEP_PAUSE, "verify gone")
    else:
        say("PlayDeck not in list — skip uninstall")

    dlg.close()
    ensure_visible(window, app)
    linger(app, window, STEP_PAUSE, "landing before Discover")

    source = next(p for p in REDISCOVER_CANDIDATES if p.is_file())
    say(f"Discover → {source.name}")
    pick = PickInstallFileDialog(window)
    apply_system_theme(pick)
    pick.show()
    ensure_visible(pick, app)
    pick._stop_icon_workers()
    linger(app, pick, STEP_PAUSE, "Discover open")

    chosen = None
    for i in range(pick.list.count()):
        item = pick.list.item(i)
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and "playdeck" in str(path).lower() and "remix" in str(path).lower():
            pick.list.setCurrentItem(item)
            chosen = str(path)
            break
    if not chosen:
        chosen = str(source)
    say(f"Selected {chosen}")
    linger(app, pick, STEP_PAUSE, "before Discover Install")

    pick._stop_icon_workers()
    pick.file_chosen.connect(window._handle_file_input)
    if pick.list.currentItem() is not None and pick.install_btn.isEnabled():
        pick.install_btn.click()
    else:
        pick.file_chosen.emit(chosen)
        pick.accept()
    app.processEvents()

    for _ in range(120):
        ensure_visible(window, app)
        app.processEvents()
        if window.stack.currentIndex() == 1:
            break
        time.sleep(0.05)

    if window.stack.currentIndex() != 1:
        say(f"FAIL no confirm stack={window.stack.currentIndex()}")
        return 1

    say(f"Confirm: {window.confirmation_view.name_label.text()!r}")
    linger(app, window, STEP_PAUSE, "confirmation")

    say("Install — watch progress page for name/version/%")
    window.confirmation_view.install_btn.click()
    app.processEvents()

    progress_snapshots = []
    t0 = time.monotonic()
    result = None
    saw_progress_page = False

    while True:
        ensure_visible(window, app)
        app.processEvents()
        elapsed = time.monotonic() - t0
        idx = window.stack.currentIndex()

        if idx == 2:
            saw_progress_page = True
            pv = window.progress_view
            snap = {
                "t": round(elapsed, 2),
                "name": pv.name_label.text(),
                "version": pv.version_label.text(),
                "format": pv.format_label.text(),
                "meta": pv.meta_label.text()[:80],
                "status": pv.status_label.text(),
                "percent_label": pv.percent_label.text(),
                "bar": pv.progress_bar.value(),
                "card_effect": pv.card.graphicsEffect(),
                "visible": pv.isVisible() and pv.card.isVisible(),
            }
            if not progress_snapshots or progress_snapshots[-1].get("bar") != snap["bar"]:
                progress_snapshots.append(snap)
                say(
                    f"PROGRESS visible={snap['visible']} "
                    f"name={snap['name']!r} ver={snap['version']!r} "
                    f"fmt={snap['format']!r} pct={snap['percent_label']} "
                    f"bar={snap['bar']} status={snap['status']!r}"
                )
                if snap["card_effect"] is not None:
                    say("WARN: card still has graphicsEffect (blank risk)")

        if idx == 3:
            result = window._current_install_result
            say(f"Result at t={elapsed:.1f}s")
            break
        if elapsed >= 180:
            say("TIMEOUT")
            break
        time.sleep(0.05)

    elapsed = time.monotonic() - t0
    if elapsed < INSTALL_MIN_WATCH:
        linger(app, window, INSTALL_MIN_WATCH - elapsed, "hold ≥35s")
    else:
        linger(app, window, STEP_PAUSE, "result")

    ok = bool(result and result.success) and saw_progress_page and bool(progress_snapshots)
    # Validate snapshot content
    if progress_snapshots:
        first = progress_snapshots[0]
        if "PlayDeck" not in first["name"]:
            say(f"WARN: unexpected name {first['name']!r}")
            ok = False
        if first["bar"] < 1:
            say("WARN: percent bar < 1")
            ok = False
        if not first["visible"]:
            say("FAIL: progress page not visible")
            ok = False

    say(f"Registry: { {a.id: a.name for a in registry.list_apps()} }")
    say(f"Snapshots captured: {len(progress_snapshots)}")
    say("SUCCESS" if ok else "FAIL")
    linger(app, window, STEP_PAUSE, "closing")
    window.close()
    app.processEvents()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
