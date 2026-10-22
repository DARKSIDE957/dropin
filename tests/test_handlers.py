"""
Unit tests for package handlers (AppImage, DEB, RPM, Flatpak, Archive).
"""

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dropin.core.models import AppPackageInfo, DistributionInfo, PackageFormat
from dropin.handlers.appimage import AppImageHandler
from dropin.handlers.deb import DebHandler
from dropin.handlers.rpm import RpmHandler
from dropin.handlers.flatpak import FlatpakHandler
from dropin.handlers.archive import ArchiveHandler
from dropin.handlers.snap import SnapHandler
from dropin.handlers.system_pkg import SystemPkgHandler
from dropin.handlers import detect_and_inspect, get_handlers


def _distro(**overrides) -> DistributionInfo:
    base = dict(
        id="fedora",
        name="Fedora Linux",
        version="44",
        id_like=[],
        arch="x86_64",
        has_dnf=True,
        has_rpm=True,
        has_pkexec=True,
        is_atomic=False,
        has_rpm_ostree=False,
    )
    base.update(overrides)
    return DistributionInfo(**base)


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestHandlers(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_appimage_handler_detection(self):
        handler = AppImageHandler()
        dummy_file = self.work_dir / "TestApp-1.0-x86_64.AppImage"
        # Write dummy ELF header with AppImage Type 2 magic: 0x7f, 'E', 'L', 'F', ... 'A', 'I', 0x02
        header = b"\x7fELF" + b"\x02\x01\x01\x00" + b"AI\x02" + b"\x00\x00\x00\x00\x00" + b"\x02\x00\x3e\x00"
        dummy_file.write_bytes(header + b"\x00" * 100)

        self.assertTrue(handler.can_handle(dummy_file))
        info = handler.inspect(dummy_file)
        self.assertEqual(info.format, PackageFormat.APPIMAGE)
        self.assertEqual(info.architecture, "x86_64")
        self.assertEqual(info.name, "TestApp")

    def test_flatpakref_handler(self):
        handler = FlatpakHandler()
        ref_file = self.work_dir / "org.example.App.flatpakref"
        content = (
            "[Flatpak Ref]\n"
            "Name=org.example.App\n"
            "Branch=stable\n"
            "Title=Example Application\n"
            "Url=https://flathub.org/repo/\n"
            "IsRuntime=false\n"
        )
        ref_file.write_text(content, encoding="utf-8")

        self.assertTrue(handler.can_handle(ref_file))
        info = handler.inspect(ref_file)
        self.assertEqual(info.format, PackageFormat.FLATPAK)
        self.assertEqual(info.name, "Example Application")
        self.assertEqual(info.version, "stable")

    def test_deb_handler_control_parsing(self):
        handler = DebHandler()
        deb_file = self.work_dir / "sample_1.0.0_amd64.deb"

        # Create control tar archive in memory
        control_content = (
            "Package: sample-app\n"
            "Version: 1.0.0\n"
            "Architecture: amd64\n"
            "Maintainer: Sample Maintainer <sample@example.com>\n"
            "Description: Sample application for testing\n"
            "Homepage: https://example.com\n"
        ).encode("utf-8")

        tar_buf = io.BytesIO()
        with tarfile.open(fileobj=tar_buf, mode="w:gz") as tf:
            ti = tarfile.TarInfo(name="control")
            ti.size = len(control_content)
            tf.addfile(ti, io.BytesIO(control_content))

        control_tar_bytes = tar_buf.getvalue()

        # Construct ar archive: !<arch>\n
        # 1. debian-binary (4 bytes: "2.0\n")
        # 2. control.tar.gz
        def make_ar_header(name: str, size: int) -> bytes:
            return f"{name:<16}0           0     0     100644  {size:<10}`\n".encode("ascii")

        ar_buf = io.BytesIO()
        ar_buf.write(b"!<arch>\n")
        
        ar_buf.write(make_ar_header("debian-binary", 4))
        ar_buf.write(b"2.0\n")

        ar_buf.write(make_ar_header("control.tar.gz", len(control_tar_bytes)))
        ar_buf.write(control_tar_bytes)
        if len(control_tar_bytes) % 2 != 0:
            ar_buf.write(b"\n")

        deb_file.write_bytes(ar_buf.getvalue())

        self.assertTrue(handler.can_handle(deb_file))
        info = handler.inspect(deb_file)
        self.assertEqual(info.format, PackageFormat.DEB)
        self.assertEqual(info.name, "sample-app")
        self.assertEqual(info.version, "1.0.0")
        self.assertEqual(info.architecture, "amd64")

    def test_archive_rejects_source_tree(self):
        handler = ArchiveHandler()
        src_archive = self.work_dir / "source-code-project.tar.gz"

        with tarfile.open(src_archive, "w:gz") as tf:
            ti = tarfile.TarInfo(name="CMakeLists.txt")
            data = b"project(SourceProject)"
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))

            ti2 = tarfile.TarInfo(name="main.c")
            data2 = b"int main() { return 0; }"
            ti2.size = len(data2)
            tf.addfile(ti2, io.BytesIO(data2))

        self.assertTrue(handler.can_handle(src_archive))
        info = handler.inspect(src_archive)
        self.assertEqual(info.format, PackageFormat.ARCHIVE)
        self.assertFalse(info.compatibility_ok)
        self.assertIn("source code", info.compatibility_reason.lower())

    def _rpm_info(self, work_dir: Path, **meta_overrides) -> AppPackageInfo:
        src = work_dir / "chatgpt.rpm"
        src.write_bytes(b"\xed\xab\xee\xdb")
        meta = {"already_installed": False}
        meta.update(meta_overrides)
        return AppPackageInfo(
            name="chatgpt",
            version="26.0-1",
            format=PackageFormat.RPM,
            architecture="x86_64",
            file_path=str(src),
            extra_metadata=meta,
        )

    def test_rpm_atomic_install_uses_rpm_ostree_not_dnf(self):
        handler = RpmHandler()
        info = self._rpm_info(self.work_dir)
        atomic = _distro(
            id="bazzite", name="Bazzite", is_atomic=True, has_rpm_ostree=True
        )
        with mock.patch(
            "dropin.handlers.rpm.get_current_distribution", return_value=atomic
        ), mock.patch.object(
            RpmHandler, "_query_installed_version", return_value=None
        ), mock.patch.object(
            RpmHandler,
            "_missing_dependencies",
            return_value=["(python3-libdnf5 if libdnf5)"],
        ), mock.patch(
            "dropin.handlers.rpm.subprocess.run", return_value=_FakeProc(0)
        ) as run:
            result = handler.install(info)

        self.assertTrue(result.success, result.error_details)
        cmd = run.call_args[0][0]
        self.assertIn("rpm-ostree", cmd)
        self.assertNotIn("dnf", cmd)
        self.assertIn("Restart", result.message)

    def test_rpm_refuses_duplicate_install(self):
        handler = RpmHandler()
        info = self._rpm_info(self.work_dir)
        with mock.patch(
            "dropin.handlers.rpm.get_current_distribution", return_value=_distro()
        ), mock.patch.object(
            RpmHandler, "_query_installed_version", return_value="26.0-1"
        ), mock.patch(
            "dropin.handlers.rpm.subprocess.run"
        ) as run:
            result = handler.install(info)

        self.assertFalse(result.success)
        self.assertIn("already installed", result.message)
        run.assert_not_called()

    def test_rpm_missing_dep_named_on_rpm_only_system(self):
        handler = RpmHandler()
        info = self._rpm_info(self.work_dir)
        rpm_only = _distro(has_dnf=False)
        with mock.patch(
            "dropin.handlers.rpm.get_current_distribution", return_value=rpm_only
        ), mock.patch.object(
            RpmHandler, "_query_installed_version", return_value=None
        ), mock.patch.object(
            RpmHandler,
            "_missing_dependencies",
            return_value=["(python3-libdnf5 if libdnf5)"],
        ), mock.patch(
            "dropin.handlers.rpm.subprocess.run"
        ) as run:
            result = handler.install(info)

        self.assertFalse(result.success)
        self.assertIn("python3-libdnf5", result.message)
        self.assertIn("python3-libdnf5", result.error_details or "")
        run.assert_not_called()

    def test_rpm_inspect_marks_atomic_and_already_installed(self):
        handler = RpmHandler()
        src = self.work_dir / "chatgpt-26.0-1.x86_64.rpm"
        src.write_bytes(b"\xed\xab\xee\xdb")
        atomic = _distro(
            id="bazzite", name="Bazzite", is_atomic=True, has_rpm_ostree=True
        )
        meta = {
            "NAME": "chatgpt",
            "VERSION": "26.0",
            "RELEASE": "1",
            "ARCH": "x86_64",
            "SUMMARY": "ChatGPT",
            "URL": "",
            "VENDOR": "OpenAI",
        }
        with mock.patch(
            "dropin.handlers.rpm.get_current_distribution", return_value=atomic
        ), mock.patch.object(
            RpmHandler, "_query_rpm_metadata", return_value=meta
        ), mock.patch.object(
            RpmHandler, "_query_installed_version", return_value="26.0-1"
        ), mock.patch.object(
            RpmHandler, "_missing_dependencies", return_value=[]
        ):
            info = handler.inspect(src)

        self.assertTrue(info.compatibility_ok, info.compatibility_reason)
        self.assertTrue(info.extra_metadata["already_installed"])
        self.assertTrue(info.extra_metadata["atomic_system"])
        self.assertIn("rpm-ostree", info.target_destination)

    def test_archive_prefers_studio_sh_over_format_sh(self):
        handler = ArchiveHandler()
        tree = self.work_dir / "android-studio"
        bin_dir = tree / "bin"
        bin_dir.mkdir(parents=True)
        format_sh = bin_dir / "format.sh"
        studio_sh = bin_dir / "studio.sh"
        format_sh.write_text("#!/bin/sh\n", encoding="utf-8")
        studio_sh.write_text("#!/bin/sh\n", encoding="utf-8")
        format_sh.chmod(0o755)
        studio_sh.chmod(0o755)

        chosen = handler._find_primary_executable(tree, "Android Studio")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.name, "studio.sh")

    def test_snap_handler_detection(self):
        handler = SnapHandler()
        snap_file = self.work_dir / "TestApp.snap"
        snap_file.write_bytes(b"hsqs" + b"\x00" * 100)
        self.assertTrue(handler.can_handle(snap_file))
        # Squashfs magic is recognised even without the .snap extension,
        # and plain gzip data is not mistaken for a snap.
        no_ext = self.work_dir / "TestApp"
        no_ext.write_bytes(b"hsqs" + b"\x00" * 100)
        self.assertTrue(handler.can_handle(no_ext))
        gzip_file = self.work_dir / "archive.tar.gz"
        gzip_file.write_bytes(b"\x1f\x8b\x08\x00" + b"\x00" * 100)
        self.assertFalse(handler.can_handle(gzip_file))

    def test_snap_handler_inspect(self):
        handler = SnapHandler()
        snap_file = self.work_dir / "TestApp.snap"
        snap_file.write_bytes(b"\\x1f\\x8b\\x08\\x00" + b"\\x00" * 100)
        distro = _distro()
        with mock.patch(
            "dropin.handlers.snap.get_current_distribution", return_value=distro
        ), mock.patch.object(SnapHandler, "_read_snap_meta", return_value=None):
            info = handler.inspect(snap_file)
        self.assertEqual(info.format, PackageFormat.SNAP)
        self.assertEqual(info.name, "TestApp")
        self.assertTrue(info.requires_root)

    def test_system_pkg_can_handle_returns_false(self):
        handler = SystemPkgHandler()
        self.assertFalse(handler.can_handle(Path("/some/file.deb")))

    def test_system_pkg_detects_package_manager(self):
        pm = SystemPkgHandler.detect_package_manager()
        # On any system with apt/dnf/pacman/etc., this should return a dict.
        if pm:
            self.assertIn("name", pm)
            self.assertIn("install", pm)

    def test_system_pkg_rejects_bad_package_names(self):
        handler = SystemPkgHandler()
        for bad in ("foo bar", "--installroot=/tmp", "-y", "pkg;rm"):
            info = AppPackageInfo(
                name=bad,
                version="",
                format=PackageFormat.SYSTEM_PKG,
                architecture="x86_64",
                file_path="",
            )
            with mock.patch.object(
                SystemPkgHandler,
                "detect_package_manager",
                return_value={"name": "dnf"},
            ):
                result = handler.install(info)
            self.assertFalse(result.success, bad)
            self.assertIn("package name", result.message)

    def test_system_pkg_atomic_uses_rpm_ostree(self):
        atomic = _distro(
            id="bazzite", name="Bazzite", is_atomic=True, has_rpm_ostree=True
        )
        with mock.patch(
            "dropin.handlers.system_pkg.get_current_distribution",
            return_value=atomic,
        ):
            pm = SystemPkgHandler.detect_package_manager()
        if pm:  # rpm-ostree may not exist on the test machine
            self.assertEqual(pm["name"], "rpm-ostree")

    def test_downloader_oversize_names_the_limit(self):
        from unittest.mock import MagicMock

        from dropin.network.downloader import DownloadWorker

        worker = DownloadWorker("https://example.com/big.AppImage")
        errors = []
        worker.error.connect(errors.append)

        response = MagicMock()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        response.getstatus.return_value = 200
        response.geturl.return_value = "https://example.com/big.AppImage"
        response.headers = {"Content-Length": str(40 * 1024 * 1024 * 1024)}

        with mock.patch(
            "urllib.request.urlopen", return_value=response
        ), mock.patch(
            "dropin.network.downloader.validate_final_url",
            return_value=(True, ""),
        ):
            worker.run()

        self.assertTrue(errors, "expected an oversize error")
        self.assertIn("MB", errors[0])
        self.assertNotIn("max_size_mb", errors[0])

    def test_get_handlers_includes_new(self):
        handlers = get_handlers()
        names = {type(h).__name__ for h in handlers}
        self.assertIn("SnapHandler", names)
        self.assertIn("SystemPkgHandler", names)


if __name__ == "__main__":
    unittest.main()
