# Dropin Architecture Specification

## Overview

Dropin is architected as a modular, decoupled Linux desktop utility separating the user interface from format-specific installation handlers, network resolvers, and system integrations.

```
                    ┌────────────────────────────────────────────────────────┐
                    │                      MainWindow                        │
                    │   ┌──────────────┐   ┌──────────────────────────────┐  │
                    │   │   DropZone   │   │  URL Input & GitHub Resolver │  │
                    │   └───────┬──────┘   └──────────────┬───────────────┘  │
                    └───────────┼─────────────────────────┼──────────────────┘
                                │                         │
                                ▼                         ▼
                    ┌────────────────────────────────────────────────────────┐
                    │                    Format Dispatcher                   │
                    │                (detect_and_inspect)                    │
                    └───────────────────────────┬────────────────────────────┘
                                                │
         ┌───────────────┬──────────────────────┼───────────────────────┬───────────────┐
         ▼               ▼                      ▼                       ▼               ▼
  ┌─────────────┐ ┌─────────────┐        ┌─────────────┐         ┌─────────────┐ ┌─────────────┐
  │  AppImage   │ │   Debian    │        │     RPM     │         │   Flatpak   │ │   Archive   │
  │   Handler   │ │   Handler   │        │   Handler   │         │   Handler   │ │   Handler   │
  └──────┬──────┘ └──────┬──────┘        └──────┬──────┘         └──────┬──────┘ └──────┬──────┘
         │               │                      │                       │               │
         ▼               ▼                      ▼                       ▼               ▼
  ~/Applications     pkexec apt             pkexec dnf           flatpak install   ~/.local/share/
  + XDG Launcher   (Debian/Ubuntu)       (Fedora/openSUSE)        (--user/system)  dropin/portable
         │               │                      │                       │               │
         └───────────────┴──────────────────────┼───────────────────────┴───────────────┘
                                                │
                                                ▼
                                 ┌─────────────────────────────┐
                                 │     SQLite App Registry     │
                                 │       & Audit Database      │
                                 └─────────────────────────────┘
```

## Module Breakdown

1. **`dropin.core`**:
   - `models`: Dataclasses for package metadata (`AppPackageInfo`), tracking (`InstalledApp`), results (`InstallResult`), and architecture/distro context.
   - `distro`: Distribution probe inspecting `/etc/os-release` and binary capabilities (`apt`, `dnf`, `zypper`, `rpm`, `dpkg`, `flatpak`, `pkexec`).
   - `config`: XDG-compliant persistent configuration (`~/.config/dropin/settings.json`).
   - `registry`: SQLite storage (`~/.local/share/dropin/dropin.db`) recording installed applications and audit logs.
   - `security`: Network and filesystem validation, SSRF filtering, and path traversal detection.
   - `logger`: File and console logging.

2. **`dropin.handlers`**:
   - `base.BaseHandler`: Abstract interface defining `can_handle`, `inspect`, `install`, `uninstall`, and `check_update`.
   - `appimage.AppImageHandler`: ELF architecture extraction, squashfs metadata extraction, desktop file & icon generation, install to `~/Applications`.
   - `deb.DebHandler`: Pure Python `ar` & `control.tar` parser, architecture compatibility matching, native installation via `pkexec apt-get`.
   - `rpm.RpmHandler`: RPM metadata querying, architecture verification, native installation via `pkexec dnf/zypper/rpm`.
   - `flatpak.FlatpakHandler`: `.flatpakref` INI parsing, user/system scope selection, `flatpak install`.
   - `archive.ArchiveHandler`: Archive member security validation, compiled executable detection, rejection of uncompiled source repositories.

3. **`dropin.network`**:
   - `downloader`: Threaded streaming downloader with progress, speed, size limits, and user cancellation.
   - `github`: GitHub repository and release asset resolver, compatible asset ranking.
   - `url_resolver`: Dispatches URLs between direct download and GitHub release pipelines.

4. **`dropin.updater`**:
   - `manager`: Multi-source update checking against GitHub releases, Flatpak remotes, and native package managers.

5. **`dropin.ui`**:
   - `main_window`: Compact primary interface coordinating drop zone, URL field, confirmation, progress, and results.
   - `theme`: Dynamic OS light/dark appearance detector applying tailored QSS stylesheets.
   - `drop_zone`: Drag and drop widget with visual hover state and accessible file picker.
   - `confirmation_view`: Metadata and permission review card.
   - `progress_view`: Responsive progress and cancellation bar.
   - `result_view`: Success launch and error detail views.
   - `installed_dialog`: Tracked applications manager with search, launch, and uninstall.
   - `settings_dialog`: User configuration editor.
   - `audit_dialog`: Security audit trail viewer.
   - `asset_dialog`: Release package selection for multi-asset releases.
