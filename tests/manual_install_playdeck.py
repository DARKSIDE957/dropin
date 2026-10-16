#!/usr/bin/env python3
"""Install PlayDeck Remix AppImage via Dropin confirmation and watch progress."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_INSTALLED = Path.home() / ".local" / "share" / "dropin" / "app"
if _INSTALLED.is_dir():
    sys.path.insert(0, str(_INSTALLED))

if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Allow real install threads (do not set DROPIN_E2E — we need workers).
os.environ.pop("DROPIN_E2E", None)

from PySide6.QtCore import QEventLoop
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

TARGET = Path("/home/virus/Applications/PlayDeck_Remix.AppImage")
MIN_WATCH_SEC = 30
MAX_WATCH_SEC = 180


def linger(app: QApplication, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        time.sleep(0.05)


def main() -> int:
    print(f"Install tour target={TARGET}", flush=True)
    if not TARGET.is_file():
        print(f"FAIL: missing {TARGET}", flush=True)
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    from dropin.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app.processEvents()

    print("  Feeding file into inspect…", flush=True)
    window._handle_file_input(str(TARGET))
    for _ in range(100):
        app.processEvents()
        time.sleep(0.05)
        if window.stack.currentIndex() == 1:
            break

    if window.stack.currentIndex() != 1:
        print(f"FAIL: not on confirm (stack={window.stack.currentIndex()})", flush=True)
        window.close()
        return 1

    name = window.confirmation_view.name_label.text()
    print(f"  Confirm: {name!r} — clicking Install", flush=True)
    window.confirmation_view.install_btn.setFocus()
    app.processEvents()
    # Activate Install (programmatic click = same slot as button press)
    window.confirmation_view.install_btn.click()
    app.processEvents()

    started = False
    progress_samples = []
    t0 = time.monotonic()
    final_idx = None
    last_status = ""

    while True:
        app.processEvents()
        elapsed = time.monotonic() - t0
        idx = window.stack.currentIndex()
        final_idx = idx

        if idx == 2:  # progress
            started = True
            title = window.progress_view.title_label.text()
            status = window.progress_view.status_label.text()
            # progress bar value if available
            pct = None
            if hasattr(window.progress_view, "progress_bar"):
                pct = window.progress_view.progress_bar.value()
            sample = f"t={elapsed:.1f}s title={title!r} status={status!r} pct={pct}"
            if status != last_status or len(progress_samples) < 3:
                print(f"  PROGRESS {sample}", flush=True)
                progress_samples.append(sample)
                last_status = status
        elif idx == 3:  # result
            print(f"  RESULT page at t={elapsed:.1f}s", flush=True)
            break
        elif idx == 1 and elapsed > 2:
            # Still on confirm — install may not have started
            if elapsed > 5 and not started:
                print("  WARN: still on confirm after 5s", flush=True)

        if elapsed >= MAX_WATCH_SEC:
            print(f"  TIMEOUT after {MAX_WATCH_SEC}s stack={idx}", flush=True)
            break
        # Ensure we watch at least MIN_WATCH_SEC even if fast
        if idx == 3 and elapsed < MIN_WATCH_SEC:
            print(f"  Result early; lingering to reach {MIN_WATCH_SEC}s watch…", flush=True)
            linger(app, MIN_WATCH_SEC - elapsed)
            break

        time.sleep(0.1)

    # If still on progress after min watch, keep going until result/timeout (loop handles)
    # Collect result details
    result_info = {}
    if window.stack.currentIndex() == 3:
        rv = window.result_view
        result_info = {
            "title": getattr(rv, "title_label", None) and rv.title_label.text(),
            "message": getattr(rv, "message_label", None) and rv.message_label.text(),
            "success": None,
        }
        if window._current_install_result is not None:
            r = window._current_install_result
            result_info["success"] = r.success
            result_info["message"] = r.message
            result_info["error_details"] = r.error_details
            result_info["installed_path"] = r.installed_path
            result_info["app_id"] = r.app_id
        print(f"  Final result: {result_info}", flush=True)
    else:
        print(
            f"  Final stack={window.stack.currentIndex()} started={started} "
            f"samples={len(progress_samples)}",
            flush=True,
        )

    # Stay briefly so user/agent can observe
    linger(app, 2.0)
    window.close()
    app.processEvents()
    time.sleep(0.5)

    ok = bool(result_info.get("success"))
    print("PASS" if ok else "FAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
