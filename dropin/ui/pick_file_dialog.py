"""
Discover installable packages on this computer.

Fast scan of common locations (Downloads, Desktop, Applications, home, …),
shows each app with its logo when available, Install on click.
No drag-and-drop and no folder picker.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, Signal, QThread, QObject, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QWidget,
)

from dropin.core.distro import get_current_distribution
from dropin.core.logger import get_logger
from dropin.core.models import PackageFormat
from dropin.handlers import detect_and_inspect
from dropin.ui.icons import icon_for

# QThreads that outlived Discover close. Keeping a strong ref prevents Qt's
# fatal "QThread: Destroyed while thread is still running" abort when a worker
# is blocked in slow I/O (e.g. inspecting a multi-GB .tar.gz).
_LINGERING_ICON_THREADS: List[QThread] = []

# Skip full inspect for archives / huge files in icon workers — tar getmembers()
# on Android Studio (~1.5GB) blocks for seconds and cannot be interrupted by quit().
_ICON_INSPECT_MAX_BYTES = 80 * 1024 * 1024


def _reap_lingering_icon_threads() -> None:
    alive: List[QThread] = []
    for thread in _LINGERING_ICON_THREADS:
        try:
            if thread.isRunning():
                alive.append(thread)
        except RuntimeError:
            pass
    _LINGERING_ICON_THREADS[:] = alive


def _format_compatible_here(fmt: PackageFormat) -> bool:
    """Hide formats this distro clearly cannot install (e.g. .deb on Fedora/Bazzite)."""
    if fmt == PackageFormat.UNKNOWN:
        return False
    distro = get_current_distribution()
    if fmt == PackageFormat.DEB:
        return bool(distro.is_debian_family or distro.has_apt or distro.has_dpkg)
    if fmt == PackageFormat.RPM:
        return bool(
            distro.is_fedora_family
            or distro.is_suse_family
            or distro.has_dnf
            or distro.has_rpm
            or distro.has_zypper
        )
    return True


def _is_installable(path: Path) -> bool:
    fmt = PackageFormat.from_extension(path.name)
    return _format_compatible_here(fmt)


def _format_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _scan_targets() -> List[Tuple[Path, int]]:
    """
    Fast targets: (directory, max_depth).
    Depth 0 = files in that folder only; 1 = one subfolder level; 2 = two.
    """
    home = Path.home()
    user = os.environ.get("USER") or home.name
    targets: List[Tuple[Path, int]] = [
        (home / "Downloads", 2),
        (home / "downloads", 2),
        (home / "Desktop", 1),
        (home / "desktop", 1),
        (home / "Applications", 2),
        (home / ".local" / "bin", 0),
        (home, 0),  # packages sitting directly in $HOME
        (Path("/opt"), 1),
        (Path(f"/run/media/{user}"), 2),
        (Path("/media"), 2),
        (Path("/mnt"), 1),
    ]
    if os.environ.get("XDG_DOWNLOAD_DIR"):
        targets.insert(0, (Path(os.environ["XDG_DOWNLOAD_DIR"]), 2))

    out: List[Tuple[Path, int]] = []
    seen: Set[str] = set()
    for path, depth in targets:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_dir():
            continue
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        out.append((resolved, depth))
    return out


def _add_file(path: Path, found: List[Tuple[float, Path]]) -> None:
    if not path.is_file() or not _is_installable(path):
        return
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    found.append((mtime, path))


def _collect(root: Path, max_depth: int, found: List[Tuple[float, Path]]) -> None:
    try:
        entries = list(root.iterdir())
    except OSError:
        return

    for entry in entries:
        if entry.is_file():
            _add_file(entry, found)

    if max_depth < 1:
        return

    for sub in entries:
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        try:
            children = list(sub.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_file():
                _add_file(child, found)
        if max_depth < 2:
            continue
        for nest in children:
            if not nest.is_dir() or nest.name.startswith("."):
                continue
            try:
                for deep in nest.iterdir():
                    if deep.is_file():
                        _add_file(deep, found)
            except OSError:
                continue


def scan_installable_files(
    roots: Iterable[Tuple[Path, int]] | Iterable[Path] | None = None,
    *,
    max_files: int = 200,
) -> List[Path]:
    """Find installable packages quickly (newest first)."""
    found: List[Tuple[float, Path]] = []

    if roots is None:
        specs = _scan_targets()
    else:
        specs = []
        for item in roots:
            if isinstance(item, tuple):
                specs.append(item)
            else:
                specs.append((item, 2))

    for root, depth in specs:
        if root.is_dir():
            _collect(root, depth, found)

    unique: dict[str, Tuple[float, Path]] = {}
    for mtime, path in found:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        prev = unique.get(key)
        if prev is None or mtime > prev[0]:
            unique[key] = (mtime, path)

    ordered = sorted(unique.values(), key=lambda t: t[0], reverse=True)
    return [p for _, p in ordered[:max_files]]


class _IconWorker(QObject):
    """Load package display name + logo for one path (background)."""

    ready = Signal(str, str, object)  # path, display_name, QPixmap|None

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        path = Path(self.path)
        raw_name = path.name
        for ext in (".tar.gz", ".tar.xz", ".tar.bz2", ".tgz", ".zip"):
            if raw_name.lower().endswith(ext):
                raw_name = raw_name[: -len(ext)]
                break
        else:
            raw_name = path.stem
        display = raw_name.replace("-", " ").replace("_", " ").strip() or path.name
        pixmap = None
        try:
            fmt = PackageFormat.from_extension(path.name)
            size = path.stat().st_size if path.is_file() else 0
            # Full inspect of portable archives walks every tar member. On a
            # 1.5GB Android Studio bundle that blocks this QThread for many
            # seconds; Discover close then ABRTs Dropin. Use the filename only.
            if fmt == PackageFormat.ARCHIVE or size > _ICON_INSPECT_MAX_BYTES:
                label = display.title() if display.islower() else display
                self.ready.emit(self.path, label, None)
                return

            info = detect_and_inspect(path)
            if info.name:
                display = info.name
            pix = QPixmap()
            if info.icon_bytes:
                pix.loadFromData(info.icon_bytes)
            elif info.icon_path and Path(info.icon_path).is_file():
                pix = QPixmap(info.icon_path)
            if not pix.isNull():
                pixmap = pix.scaled(
                    40,
                    40,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        except Exception:
            pass
        self.ready.emit(self.path, display, pixmap)


class PackageRow(QWidget):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setObjectName("iconSlot")
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setPixmap(icon_for("download", size=64).pixmap(QSize(22, 22)))
        layout.addWidget(self.icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title = QLabel(path.stem, self)
        self.title.setStyleSheet("font-weight: 700; background: transparent;")
        text_col.addWidget(self.title)

        fmt = PackageFormat.from_extension(path.name)
        try:
            size = _format_size(path.stat().st_size)
        except OSError:
            size = "?"
        folder = path.parent.name or str(path.parent)
        self.sub = QLabel(f"{fmt.value},  {size},  {folder}", self)
        self.sub.setObjectName("mutedLabel")
        self.sub.setWordWrap(True)
        text_col.addWidget(self.sub)
        layout.addLayout(text_col, 1)

    def set_logo(self, name: str, pixmap: Optional[QPixmap]):
        if name:
            self.title.setText(name)
        if pixmap is not None and not pixmap.isNull():
            self.icon_label.setPixmap(pixmap)


class PickInstallFileDialog(QDialog):
    """List installable packages; user installs one."""

    file_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discover packages")
        self.setMinimumSize(520, 460)
        self.resize(560, 520)
        self._icon_threads: List[QThread] = []
        self._icon_queue: List[str] = []
        self._icons_inflight = 0
        self._max_icon_workers = 2
        self._icons_stopping = False
        _reap_lingering_icon_threads()
        self._rows: dict[str, PackageRow] = {}
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Packages ready to install", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.hint = QLabel(
            "Installable packages found on this computer. Select one, then click Install.",
            self,
        )
        self.hint.setObjectName("mutedLabel")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.list = QListWidget(self)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setSpacing(4)
        self.list.itemDoubleClicked.connect(self._accept_current)
        self.list.itemSelectionChanged.connect(self._sync_install_enabled)
        layout.addWidget(self.list, 1)

        self.empty_label = QLabel(
            "No installable packages found yet.\n"
            "Put an AppImage, .deb, .rpm, or Flatpak in Downloads or Desktop, then Refresh.",
            self,
        )
        self.empty_label.setObjectName("mutedLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.setObjectName("compactBtn")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh)
        btn_row.addWidget(self.refresh_btn)

        btn_row.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Install", self)
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.install_btn.setEnabled(False)
        self.install_btn.clicked.connect(self._accept_current)
        btn_row.addWidget(self.install_btn)

        layout.addLayout(btn_row)

    def refresh(self):
        """Scan synchronously — should finish in well under a second."""
        self._stop_icon_workers()
        # _stop_icon_workers latches _icons_stopping so close/accept cannot
        # start new workers. Refresh must clear that latch or the icon queue
        # never drains (queue fills, threads stay 0).
        self._icons_stopping = False
        self.list.clear()
        self._rows.clear()
        self._icon_queue.clear()

        paths = scan_installable_files()

        if not paths:
            self.list.hide()
            self.empty_label.show()
            self.hint.setText("No installable packages found on this computer.")
            self.install_btn.setEnabled(False)
            return

        self.empty_label.hide()
        self.list.show()
        self.hint.setText(
            f"Found {len(paths)} package(s). Select one, then click Install."
        )

        for path in paths:
            path_str = str(path)
            row = PackageRow(path, self.list)
            item = QListWidgetItem(self.list)
            item.setData(Qt.ItemDataRole.UserRole, path_str)
            item.setToolTip(path_str)
            item.setSizeHint(QSize(0, 56))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows[path_str] = row
            self._icon_queue.append(path_str)

        self._sync_install_enabled()
        # Skip background icon QThreads under E2E — they SEGV'd during long pauses.
        if os.environ.get("DROPIN_E2E") != "1":
            self._pump_icon_queue()

    def _pump_icon_queue(self):
        if self._icons_stopping:
            return
        while self._icons_inflight < self._max_icon_workers and self._icon_queue:
            path_str = self._icon_queue.pop(0)
            self._icons_inflight += 1
            # Do NOT parent QThread to this dialog — accepting/closing while a
            # child thread is still running aborts Qt ("QThread: Destroyed
            # while thread is still running").
            thread = QThread()
            worker = _IconWorker(path_str)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.ready.connect(self._on_icon_ready)
            worker.ready.connect(thread.quit)
            thread.finished.connect(self._on_icon_thread_finished)
            # Keep worker alive for the thread lifetime
            thread._worker = worker  # type: ignore[attr-defined]
            self._icon_threads.append(thread)
            thread.start()

    def _on_icon_thread_finished(self):
        self._icons_inflight = max(0, self._icons_inflight - 1)
        # Leave finished threads in _icon_threads until _stop_icon_workers
        # quits/waits them. Filtering here dropped the last Python ref and
        # destroyed QThreads during Discover idle pauses.
        if not self._icons_stopping:
            self._pump_icon_queue()

    def _on_icon_ready(self, path_str: str, name: str, pixmap):
        if self._icons_stopping:
            return
        row = self._rows.get(path_str)
        if row is not None:
            row.set_logo(name, pixmap)

    def _stop_icon_workers(self):
        self._icons_stopping = True
        self._icon_queue.clear()
        threads = list(self._icon_threads)
        self._icon_threads.clear()
        self._icons_inflight = 0
        parked = 0
        for thread in threads:
            try:
                thread.finished.disconnect(self._on_icon_thread_finished)
            except (RuntimeError, TypeError):
                pass
            try:
                worker = getattr(thread, "_worker", None)
                if worker is not None:
                    try:
                        worker.ready.disconnect(self._on_icon_ready)
                    except (RuntimeError, TypeError):
                        pass
            except RuntimeError:
                pass
            if thread.isRunning():
                thread.quit()
                if not thread.wait(1500):
                    # Worker blocked in non-interruptible I/O. Park the thread
                    # so Python GC cannot destroy it while it is still running
                    # (that fatal Qt abort was crashing Dropin on Install/close).
                    get_logger().warning(
                        "Discover icon thread still running; parking until it finishes"
                    )
                    _LINGERING_ICON_THREADS.append(thread)
                    thread.finished.connect(_reap_lingering_icon_threads)
                    parked += 1
                    continue
        _reap_lingering_icon_threads()

    def done(self, result: int):
        self._stop_icon_workers()
        super().done(result)

    def closeEvent(self, event):
        self._stop_icon_workers()
        super().closeEvent(event)

    def _sync_install_enabled(self):
        self.install_btn.setEnabled(self.list.currentItem() is not None)

    def _accept_current(self):
        item = self.list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if not path:
            return
        # Stop workers before accept() tears the dialog down.
        self._stop_icon_workers()
        self.file_chosen.emit(str(path))
        self.accept()
