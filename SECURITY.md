# Dropin Security Policy

## Threat model

Dropin downloads and installs desktop software. Untrusted files and URLs can compromise a workstation. Controls below target that threat — not arbitrary package size.

## Real controls

### 1. Privilege separation
- The GUI runs as a normal user.
- Dropin never collects root passwords in custom fields.
- System packages escalate only through `pkexec` (the desktop’s Polkit agent).

### 2. Transport & SSRF protection
- By default **HTTPS is required**; cleartext HTTP can be disabled in Settings → Security.
- `file://`, `ftp://`, `javascript:`, and similar schemes are rejected.
- Hostnames resolving to loopback, link-local, multicast, or RFC-1918 private ranges are blocked (SSRF).
- Cloud metadata hostnames (e.g. `metadata.google.internal`) are blocked.
- **After redirects**, the final URL is validated again so an HTTPS host cannot bounce into a private IP or HTTP target.

### 3. Integrity (SHA-256)
- Every download is hashed with SHA-256 while streaming.
- When GitHub publishes an asset `digest` (`sha256:…`), Dropin verifies the file matches before offering Install.
- The confirmation screen shows the digest (verified or computed for your records).

### 4. Content authenticity (magic bytes)
- Downloaded bytes must match a real package format (ELF/AppImage, DEB `!<arch>`, RPM magic, ZIP/Flatpak, compressed archives, `.flatpakref`).
- HTML pages and JSON API error bodies are rejected so a phishing redirect cannot be “installed”.

### 5. Archive safety
- Archive members are checked for `../` traversal and absolute paths before extraction.
- Unsafe symlink targets outside the extract directory are blocked.

### 6. Source builds rejected
- Dropin will not compile arbitrary source trees (`CMakeLists.txt`, `Makefile`, etc.).
- Only prebuilt packages and portable binaries are accepted.

### 7. Confirmation & audit
- Installations show a confirmation screen (name, destination, permissions, integrity).
- Install, uninstall, and **update checks** are logged under Settings → Security → Audit Logs.

### 8. Disk-safety limit (not a security control)
- A large maximum download size exists only to avoid filling the disk by accident.
- Safe, large Linux packages are expected — raise the limit freely for trusted apps.

## How to verify the update manager

1. Install an app from a **GitHub release URL** (so Dropin stores `update_type=github`).
2. Open **Installed → Check updates**.
3. You should see a per-app result (Up to date / Update available) and a matching **UPDATE_CHECK** row in the audit log.
4. If an update exists, use **Update** to download through the same secure path (HTTPS, digest, magic bytes).

Local `.deb` / `.rpm` / AppImage drops without a GitHub/Flatpak upstream cannot invent an update channel — that is expected.
