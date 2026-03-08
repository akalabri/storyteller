"""
Async retry utilities for the storyteller pipeline.

Provides:
- async_retry      — generic async retry with configurable delays and error filters
- VeoSafetyBlockedError — raised when Veo blocks for person/face safety; triggers
                          FAL fallback in the video agent
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class VeoSafetyBlockedError(Exception):
    """Veo blocked generation due to person/face safety settings."""


class RateLimitError(Exception):
    """HTTP 429 rate-limit error wrapper."""


# ---------------------------------------------------------------------------
# Generic async retry
# ---------------------------------------------------------------------------

async def async_retry(
    fn: Callable[..., Coroutine[Any, Any, T]],
    *args: Any,
    delays: list[int | float] | None = None,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    abort_on: tuple[type[Exception], ...] = (),
    label: str = "",
    **kwargs: Any,
) -> T:
    """
    Call ``fn(*args, **kwargs)`` and retry on exceptions matching ``retry_on``.

    Parameters
    ----------
    fn:
        Async callable to invoke.
    delays:
        Seconds to wait before each retry attempt.  The number of retries
        equals ``len(delays)``.  Defaults to ``[15, 30, 60, 120]``.
    retry_on:
        Exception types that should trigger a retry.
    abort_on:
        Exception types that should re-raise immediately (no retry), even if
        they are also matched by ``retry_on``.
    label:
        Human-readable description used in log messages.
    """
    if delays is None:
        delays = [15, 30, 60, 120]

    last_exc: Exception | None = None

    for attempt, delay in enumerate(delays + [None], start=1):  # type: ignore[operator]
        try:
            return await fn(*args, **kwargs)
        except tuple(abort_on) as exc:  # type: ignore[misc]
            raise exc
        except tuple(retry_on) as exc:  # type: ignore[misc]
            last_exc = exc
            if delay is None:
                break
            logger.warning(
                "[%s] Attempt %d failed (%s). Retrying in %ss…",
                label or fn.__name__,
                attempt,
                type(exc).__name__,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Decorator version
# ---------------------------------------------------------------------------

def with_async_retry(
    delays: list[int | float] | None = None,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    abort_on: tuple[type[Exception], ...] = (),
) -> Callable[[Callable[..., Coroutine[Any, Any, T]]], Callable[..., Coroutine[Any, Any, T]]]:
    """
    Decorator that wraps an async function with retry logic.

    Usage::

        @with_async_retry(delays=[15, 30, 60], retry_on=(RateLimitError,))
        async def call_api(...):
            ...
    """
    def decorator(fn: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await async_retry(
                fn,
                *args,
                delays=delays,
                retry_on=retry_on,
                abort_on=abort_on,
                label=fn.__qualname__,
                **kwargs,
            )
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# 429 detection helpers
# ---------------------------------------------------------------------------

def is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception represents an HTTP 429 rate-limit response."""
    return "429" in str(exc) or isinstance(exc, RateLimitError)


def is_veo_internal_error(exc: Exception) -> bool:
    """Return True if the exception represents Veo internal error code 13."""
    return "code 13" in str(exc).lower() or '"code": 13' in str(exc)


def is_veo_safety_error(exc: Exception) -> bool:
    """Return True if the exception indicates a Veo safety block."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("person/face", "safety", "blocked", "safety_block"))
