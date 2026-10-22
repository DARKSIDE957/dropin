# Dropin

**Install Linux apps without the terminal.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://python.org)
[![Linux](https://img.shields.io/badge/Platform-Linux-0ea5e9.svg)](#)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Dropin-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/c/4e4397f93e)

---

## About

Dropin is a desktop app for people who find installing software on Linux confusing. It is not aimed at developers or users who are already comfortable with the terminal.

After a one-time setup, you can install packages by dropping a file onto the window, pasting a download or GitHub link, or choosing a package from Discover. Dropin confirms before installing, tracks what you installed, and can check for updates when the source supports it.

Works on Ubuntu, Fedora, Arch, openSUSE, and similar desktop distributions.

Dropin is still new and early in development. If something breaks, feels unclear, or does not work as expected, please [open an issue](https://github.com/DARKSIDE957/dropin/issues) and share what you ran into. Reports like that help a lot.

---

## Install

One command installs everything: dependencies, the app, and the menu launcher.

```bash
git clone https://github.com/DARKSIDE957/dropin.git
cd dropin
./install.sh
```

What `./install.sh` does:

1. Checks that Python 3 is available  
2. Installs required packages from `requirements.txt` (including PySide6)  
3. Copies Dropin into your account (`~/.local`)  
4. Adds Dropin to your app menu  

Then open **Dropin** from the app menu.

For all users on the machine (needs sudo): `./install.sh --system`

---

## Uninstall

```bash
./uninstall.sh
```

Removes Dropin from your account. For a system-wide install: `./uninstall.sh --system`

---

## Usage

1. Drop a package onto the window, use Discover, or paste a URL and click Install.
2. Confirm the install when prompted.
3. Manage installed apps from the Apps button; change preferences in Settings.

Supported formats: AppImage, DEB, RPM, Flatpak (`.flatpakref` / `.flatpak`), Snap (`.snap`), and portable archives (`.tar.gz`, `.tar.xz`, `.zip`) that contain a ready binary. You can also type a package name to install it from your distribution's own repositories.

---

## Updates

GitHub- and Flatpak-sourced apps can be checked under **Apps → Check updates**. Packages installed from a local file alone are not tracked for updates.

---

## Security

Downloads prefer HTTPS. Private and local network addresses are blocked. Packages are hashed (SHA-256) and checked for valid content. Admin rights are requested through `pkexec` only when needed.

See [SECURITY.md](SECURITY.md) for details.

---

## Support

If Dropin has been useful, you can support the project on Ko-fi.

[Ko-fi](https://ko-fi.com/c/4e4397f93e)

## License

Dropin is free and open source under the MIT License.

[MIT](LICENSE)
