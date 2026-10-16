# Dropin tests

## Default unit suite

```bash
python3 -m unittest discover -s tests -q
```

This discovers `test_*.py` modules only. Manual and visible tour scripts are **not** run by default.

## Manual / visible tours

These scripts drive a real GUI or long install flows. Run them yourself when iterating on UX:

| Script | Purpose |
|--------|---------|
| `e2e_keyboard_tour.py` | Keyboard-driven end-to-end tour |
| `manual_browse_tour.py` | Manual Discover / browse walkthrough |
| `manual_install_playdeck.py` | Manual install of a sample package |
| `visible_uninstall_reinstall.py` | Visible uninstall then reinstall |

Example:

```bash
python3 tests/manual_browse_tour.py
```

Set `DROPIN_E2E=1` when a tour should skip Discover background icon workers.
