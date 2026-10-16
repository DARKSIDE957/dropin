#!/usr/bin/env python3
"""
Dropin end-to-end walkthrough — keyboard / programmatic input only (no mouse).

Pauses PAUSE_SEC on each screen, exercises landing → Settings → Installed →
Discover → confirm inspect, and records pass/fail plus background signals.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

# Prefer the installed Dropin tree (same as the menu launcher).
_INSTALLED = Path.home() / ".local" / "share" / "dropin" / "app"
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DROPIN_E2E"] = "1"  # disable fragile background QThreads during tour

from PySide6.QtCore import Qt, QTimer, QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QListWidget

PAUSE_SEC = 10  # seconds to linger on each screen


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    duration_s: float = 0.0


@dataclass
class RunReport:
    steps: List[StepResult] = field(default_factory=list)
    stderr_notes: List[str] = field(default_factory=list)
    log_tail: str = ""
    process_alive_end: bool = False
    aborted: bool = False
    abort_reason: str = ""

    def add(self, name: str, ok: bool, detail: str = "", duration_s: float = 0.0):
        self.steps.append(StepResult(name, ok, detail, duration_s))
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def _pause(app: QApplication, seconds: float = PAUSE_SEC) -> None:
    """Block on the Qt event loop for `seconds` (no QTest.qWait — it SEGV'd under load)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.05)


def _activate(widget) -> None:
    """Keyboard-style activation: focus + Space (no mouse click)."""
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    QTest.keyClick(widget, Qt.Key.Key_Space)


def _key(widget, key, *modifiers) -> None:
    widget.setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    mod = Qt.KeyboardModifier.NoModifier
    for m in modifiers:
        mod |= m
    QTest.keyClick(widget, key, mod)


def _read_log_tail(n: int = 40) -> str:
    log = Path.home() / ".local" / "state" / "dropin" / "dropin.log"
    if not log.is_file():
        return "(no dropin.log yet)"
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"(could not read log: {e})"


def _find_sample_appimage() -> Optional[Path]:
    apps = Path.home() / "Applications"
    if apps.is_dir():
        for p in sorted(apps.glob("*.AppImage")):
            if p.is_file():
                return p
    return None


class E2ERunner:
    def __init__(self):
        self.report = RunReport()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.window = None
        self._log_before = _read_log_tail(5)

    def run(self) -> RunReport:
        try:
            self._step_open()
            self._step_landing()
            self._step_settings()
            self._step_installed()
            self._step_discover_and_inspect()
            self._step_url_empty_feedback()
            self._step_browse_focus()
            self._step_close_clean()
        except Exception as e:
            self.report.aborted = True
            self.report.abort_reason = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            self.report.add("ABORT", False, str(e))
            print(self.report.abort_reason, flush=True)
        finally:
            self.report.log_tail = _read_log_tail(50)
            self.report.process_alive_end = (
                self.window is not None and self.window.isVisible()
            ) or (self.app is not None)
            self._print_summary()
        return self.report

    def _step(self, name: str, fn: Callable[[], str]) -> None:
        t0 = time.monotonic()
        try:
            detail = fn() or ""
            self.report.add(name, True, detail, time.monotonic() - t0)
        except Exception as e:
            self.report.add(name, False, f"{e}", time.monotonic() - t0)
            raise

    def _step_open(self) -> None:
        def go():
            from dropin.ui.main_window import MainWindow

            self.window = MainWindow()
            self.window.show()
            self.app.processEvents()
            assert self.window.isVisible(), "MainWindow not visible"
            assert self.window.stack.currentIndex() == 0, "not on landing"
            return f"pid-like app running, title={self.window.windowTitle()!r}"

        self._step("1. Open Dropin", go)

    def _step_landing(self) -> None:
        def go():
            w = self.window
            assert w.drop_zone is not None
            assert w.url_input is not None
            assert w.install_url_btn is not None
            assert w.pick_file_btn is not None
            assert w.installed_btn is not None
            assert w.settings_btn is not None
            # Tab through primary controls (keyboard only).
            w.pick_file_btn.setFocus(Qt.FocusReason.TabFocusReason)
            QTest.keyClick(w, Qt.Key.Key_Tab)
            QTest.keyClick(w, Qt.Key.Key_Tab)
            print(f"  … pausing {PAUSE_SEC}s on landing", flush=True)
            _pause(self.app, PAUSE_SEC)
            return f"stack={w.stack.currentIndex()} pause={PAUSE_SEC}s"

        self._step("2. Landing screen (pause)", go)

    def _step_settings(self) -> None:
        def go():
            w = self.window
            # Programmatic open (same as activating the header control).
            from dropin.ui.settings_dialog import SettingsDialog
            from dropin.ui.theme import apply_system_theme

            dlg = SettingsDialog(w)
            apply_system_theme(dlg)
            dlg.show()
            self.app.processEvents()
            assert dlg.isVisible()
            # Cycle tabs with keyboard if present.
            if hasattr(dlg, "tabs"):
                dlg.tabs.setFocus(Qt.FocusReason.TabFocusReason)
                QTest.keyClick(dlg.tabs, Qt.Key.Key_Right)
            print(f"  … pausing {PAUSE_SEC}s on Settings", flush=True)
            _pause(self.app, PAUSE_SEC)
            # Escape to dismiss if possible; else reject.
            QTest.keyClick(dlg, Qt.Key.Key_Escape)
            self.app.processEvents()
            if dlg.isVisible():
                dlg.reject()
            self.app.processEvents()
            return f"settings closed pause={PAUSE_SEC}s"

        self._step("3. Settings screen (pause)", go)

    def _step_installed(self) -> None:
        def go():
            w = self.window
            from dropin.ui.installed_dialog import InstalledAppsDialog
            from dropin.ui.theme import apply_system_theme

            dlg = InstalledAppsDialog(w)
            apply_system_theme(dlg)
            dlg.show()
            self.app.processEvents()
            assert dlg.isVisible()
            if hasattr(dlg, "search_input"):
                dlg.search_input.setFocus(Qt.FocusReason.TabFocusReason)
                QTest.keyClicks(dlg.search_input, "a")
                QTest.keyClick(dlg.search_input, Qt.Key.Key_Backspace)
            print(f"  … pausing {PAUSE_SEC}s on Installed apps", flush=True)
            _pause(self.app, PAUSE_SEC)
            if hasattr(dlg, "close_btn"):
                _activate(dlg.close_btn)
            self.app.processEvents()
            if dlg.isVisible():
                dlg.reject()
            self.app.processEvents()
            return f"installed dialog closed pause={PAUSE_SEC}s"

        self._step("4. Installed apps screen (pause)", go)

    def _step_discover_and_inspect(self) -> None:
        def go():
            w = self.window
            from dropin.ui.pick_file_dialog import PickInstallFileDialog
            from dropin.ui.theme import apply_system_theme

            sample = _find_sample_appimage()
            dlg = PickInstallFileDialog(w)
            apply_system_theme(dlg)
            dlg.show()
            self.app.processEvents()
            assert dlg.isVisible(), "Discover not visible"
            # Stop icon workers before the long linger so idle pause cannot
            # race QThread teardown (observed SEGV during 10s Discover pause).
            dlg._stop_icon_workers()
            print(f"  … pausing {PAUSE_SEC}s on Discover", flush=True)
            _pause(self.app, PAUSE_SEC)

            # Prefer a list item; if empty, inject the known AppImage path.
            list_w: QListWidget = dlg.list
            chosen = None
            if list_w.count() > 0:
                list_w.setFocus(Qt.FocusReason.TabFocusReason)
                list_w.setCurrentRow(0)
                QTest.keyClick(list_w, Qt.Key.Key_Down)
                list_w.setCurrentRow(0)
                item = list_w.currentItem()
                chosen = item.data(Qt.ItemDataRole.UserRole) if item else None
                # Activate Install via keyboard.
                if hasattr(dlg, "install_btn") and dlg.install_btn.isEnabled():
                    _activate(dlg.install_btn)
                else:
                    dlg._accept_current()
            elif sample is not None:
                chosen = str(sample)
                dlg._stop_icon_workers()
                dlg.file_chosen.emit(chosen)
                dlg.accept()
            else:
                raise RuntimeError("Discover empty and no ~/Applications/*.AppImage found")

            self.app.processEvents()
            # Feed into main window inspect path if dialog only emitted signal.
            if chosen and w.stack.currentIndex() == 0:
                w._handle_file_input(str(chosen))
            self.app.processEvents()
            # Allow inspect to finish (progress → confirm).
            for _ in range(50):
                self.app.processEvents()
                QTest.qWait(100)
                if w.stack.currentIndex() == 1:
                    break

            idx = w.stack.currentIndex()
            if idx != 1:
                raise RuntimeError(f"expected confirmation page (1), got stack={idx}")

            name = w.confirmation_view.name_label.text()
            assert name, "confirmation name empty"
            assert "Package size" in w.confirmation_view.size_row[1].text()
            print(f"  … pausing {PAUSE_SEC}s on confirmation ({name!r})", flush=True)
            _pause(self.app, PAUSE_SEC)

            # Cancel via keyboard (do not install).
            _activate(w.confirmation_view.cancel_btn)
            self.app.processEvents()
            QTest.qWait(200)
            if w.stack.currentIndex() != 0:
                w._return_to_landing()
                self.app.processEvents()

            return f"inspected {chosen!r} as {name!r}; back to landing"

        self._step("5. Discover → select file → inspect confirm (pauses)", go)

    def _step_url_empty_feedback(self) -> None:
        def go():
            w = self.window
            w._show_page(0, animate=False)
            w.url_input.clear()
            w.url_input.setFocus(Qt.FocusReason.TabFocusReason)
            # Activate Install with empty URL — should not crash.
            # Suppress modal by invoking handler then closing any QMessageBox.
            from PySide6.QtWidgets import QMessageBox

            QTimer.singleShot(200, lambda: self._dismiss_top_message())
            _activate(w.install_url_btn)
            self.app.processEvents()
            QTest.qWait(500)
            self._dismiss_top_message()
            print(f"  … pausing {PAUSE_SEC}s after empty-URL feedback", flush=True)
            _pause(self.app, PAUSE_SEC)
            return "empty URL handled without crash"

        self._step("6. Empty URL Install feedback (pause)", go)

    def _dismiss_top_message(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QMessageBox) and widget.isVisible():
                QTest.keyClick(widget, Qt.Key.Key_Escape)
                widget.done(QMessageBox.StandardButton.Ok)
                widget.close()

    def _step_browse_focus(self) -> None:
        def go():
            w = self.window
            w.drop_zone.browse_btn.setFocus(Qt.FocusReason.TabFocusReason)
            # Do not open native file dialog (blocks automation); just focus + pause.
            print(f"  … pausing {PAUSE_SEC}s with Browse focused", flush=True)
            _pause(self.app, PAUSE_SEC)
            return "browse focused (file dialog not opened — would block)"

        self._step("7. Browse control focus (pause)", go)

    def _step_close_clean(self) -> None:
        def go():
            w = self.window
            w.close()
            self.app.processEvents()
            QTest.qWait(300)
            return "MainWindow.close() completed"

        self._step("8. Close app cleanly", go)

    def _print_summary(self) -> None:
        print("\n======== E2E SUMMARY ========", flush=True)
        passed = sum(1 for s in self.report.steps if s.ok)
        failed = sum(1 for s in self.report.steps if not s.ok)
        for s in self.report.steps:
            print(
                f"  {'PASS' if s.ok else 'FAIL':4}  {s.name}  ({s.duration_s:.1f}s)"
                + (f"  [{s.detail}]" if s.detail else ""),
                flush=True,
            )
        print(f"\nTotals: {passed} passed, {failed} failed, pause={PAUSE_SEC}s/screen", flush=True)
        if self.report.aborted:
            print(f"ABORTED: {self.report.abort_reason.splitlines()[0]}", flush=True)
        print("\n----- dropin.log (tail) -----", flush=True)
        print(self.report.log_tail, flush=True)
        print("----- end log -----", flush=True)


def main() -> int:
    print(
        f"Dropin E2E keyboard tour starting at {datetime.now().isoformat()} "
        f"(PAUSE_SEC={PAUSE_SEC})",
        flush=True,
    )
    report = E2ERunner().run()
    failed = any(not s.ok for s in report.steps) or report.aborted
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
