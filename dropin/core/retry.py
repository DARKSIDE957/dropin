"""
Retry logic with exponential backoff for Dropin network operations.

Makes downloads and API calls resilient to transient network failures.
"""

from __future__ import annotations

import time
import random
from typing import Callable, TypeVar, Tuple, Optional

from dropin.core.logger import get_logger

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Optional[Tuple[type, ...]] = None,
    on_retry: Optional[Callable[[int, Exception], None]] = None,
) -> T:
    """
    Call func, retrying with exponential backoff on transient failures.

    Args:
        func: Callable to retry.
        max_retries: Maximum number of retry attempts (not counting the first try).
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        retry_on: Exception types to retry on (default: OSError, ConnectionError).
        on_retry: Optional callback(attempt_number, exception) before each retry.

    Returns:
        The result of func on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    if retry_on is None:
        retry_on = (OSError, ConnectionError)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except retry_on as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            delay = min(base_delay * (2 ** attempt) + random.uniform(0, 0.5), max_delay)
            get_logger().warning(
                f"Attempt {attempt + 1} failed: {exc}. Retrying in {delay:.1f}s…"
            )
            if on_retry:
                try:
                    on_retry(attempt + 1, exc)
                except Exception:
                    pass
            time.sleep(delay)
        except Exception:
            # Non-retryable exceptions propagate immediately.
            raise

    assert last_exc is not None
    raise last_exc