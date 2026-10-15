"""
Audit logging for Dropin application events.
"""

import logging
import os
from pathlib import Path
from typing import Optional


def get_log_dir() -> Path:
    xdg_state_home = os.environ.get("XDG_STATE_HOME")
    if xdg_state_home:
        path = Path(xdg_state_home) / "dropin"
    else:
        path = Path.home() / ".local" / "state" / "dropin"
    path.mkdir(parents=True, exist_ok=True)
    return path


_LOGGER: Optional[logging.Logger] = None


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    logger = logging.getLogger("dropin")
    logger.setLevel(logging.INFO)

    log_dir = get_log_dir()
    log_file = log_dir / "dropin.log"

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    try:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        pass

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    _LOGGER = logger
    return _LOGGER
