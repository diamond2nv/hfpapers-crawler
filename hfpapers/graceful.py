#!/usr/bin/env python3
# hfpapers/graceful.py — Graceful shutdown helpers for CLI
# Handles Ctrl+C (SIGINT) and Ctrl+Z (SIGTSTP) gracefully
# Designed for entry points that might trigger long-running async operations

import asyncio
import logging
import os
import signal
import sys
import threading
from types import FrameType
from typing import Optional, Set

logger = logging.getLogger("hfpapers.graceful")

# ── Global state ───────────────────────────────────────────

_shutting_down: bool = False
_interrupted: bool = False
_shutdown_hooks: list = []  # (name, callable) pairs
_active_asyncio_tasks: Set[asyncio.Task] = set()
_shutdown_lock = threading.Lock()
_original_sigint: Optional[callable] = None
_original_sigtstp: Optional[callable] = None


# ── Public API ─────────────────────────────────────────────


def is_shutting_down() -> bool:
    """Returns True if shutdown has been requested (Ctrl+C or similar)."""
    return _shutting_down


def was_interrupted() -> bool:
    """Returns True if the interruption was a Ctrl+C (not Ctrl+Z)."""
    return _interrupted


def register_shutdown_hook(name: str, fn: callable):
    """Register a cleanup function to call during graceful shutdown.

    Args:
        name: Human-readable name for logging
        fn: Zero-argument callable; will be called during shutdown
    """
    _shutdown_hooks.append((name, fn))


def run_async_with_graceful_shutdown(
    coro,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    graceful_timeout: float = 3.0,
) -> Optional[object]:
    """Run an async coroutine in a new event loop with graceful Ctrl+C/Ctrl+Z handling.

    This replaces the standard ``loop.run_until_complete(coro)`` pattern
    which produces messy tracebacks on interruption.

    Args:
        coro: The async coroutine to run
        loop: Optional existing event loop; if None, creates a new one
        graceful_timeout: Seconds to wait for cleanup before forced exit

    Returns:
        The coroutine result, or None if interrupted
    """
    close_loop = False
    if loop is None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        close_loop = True

    try:
        _install_signal_handlers(loop)
        task = loop.create_task(coro)

        def _cancel_on_interrupt():
            """Signal-safe cancellation from signal handler thread."""
            if not task.done():
                task.cancel()
            _cleanup_sessions()

        register_shutdown_hook("cancel-asyncio-tasks", _cancel_on_interrupt)

        try:
            result = loop.run_until_complete(task)
            return result
        except asyncio.CancelledError:
            logger.info("Task cancelled by user (Ctrl+C)")
            return None

    finally:
        _run_shutdown_hooks(graceful_timeout)
        if close_loop:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
        _restore_signal_handlers()


def run_in_executor_with_graceful(
    fn: callable,
    *args,
    timeout: Optional[float] = None,
    **kwargs,
):
    """Run a blocking function in a thread with graceful interruption.

    Used for functions called via ``loop.run_in_executor()`` that may hang.

    Args:
        fn: Blocking callable
        timeout: Optional timeout in seconds
        args, kwargs: Passed to fn

    Returns:
        fn result, or None if interrupted/timed out
    """
    result: list = []
    exception: list = []
    event = threading.Event()

    def _wrapper():
        try:
            result.append(fn(*args, **kwargs))
        except BaseException as e:
            exception.append(e)
        finally:
            event.set()

    t = threading.Thread(target=_wrapper, daemon=True)
    t.start()

    if not event.wait(timeout=timeout):
        # Timed out — return None silently
        logger.warning(f"Executor call timed out after {timeout}s: {fn.__name__}")
        return None

    if exception:
        raise exception[0]
    return result[0] if result else None


# ── Signal Handlers ────────────────────────────────────────


def _install_signal_handlers(loop: asyncio.AbstractEventLoop):
    """Install SIGINT and SIGTSTP handlers for graceful shutdown."""
    global _original_sigint, _original_sigtstp

    def _sigint_handler(signum: int, frame: Optional[FrameType]):
        """Ctrl+C handler — graceful shutdown."""
        global _shutting_down, _interrupted
        with _shutdown_lock:
            if _shutting_down:
                # Second Ctrl+C -> force exit
                logger.warning("Forced exit (second Ctrl+C)")
                sys.stderr.write("\n")
                sys.stderr.flush()
                os._exit(1)
            _shutting_down = True
            _interrupted = True

        loop.call_soon_threadsafe(_cancel_all_asyncio_tasks, loop)
        sys.stderr.write("\n")
        sys.stderr.flush()

    def _sigtstp_handler(signum: int, frame: Optional[FrameType]):
        """Ctrl+Z handler — suspend gracefully then continue."""
        global _shutting_down, _interrupted
        with _shutdown_lock:
            if _shutting_down:
                return
            _shutting_down = True
            _interrupted = False

        loop.call_soon_threadsafe(_cancel_all_asyncio_tasks, loop)
        sys.stderr.write("\n")
        sys.stderr.flush()

    _original_sigint = signal.signal(signal.SIGINT, _sigint_handler)
    _original_sigtstp = signal.signal(signal.SIGTSTP, _sigtstp_handler)


def _restore_signal_handlers():
    """Restore original signal handlers."""
    global _original_sigint, _original_sigtstp
    try:
        if _original_sigint is not None:
            signal.signal(signal.SIGINT, _original_sigint)
            _original_sigint = None
        if _original_sigtstp is not None:
            signal.signal(signal.SIGTSTP, _original_sigtstp)
            _original_sigtstp = None
    except ValueError:
        pass  # Not in main thread, can't restore


def _cancel_all_asyncio_tasks(loop: asyncio.AbstractEventLoop):
    """Cancel all running asyncio tasks."""
    for task in asyncio.all_tasks(loop=loop):
        if not task.done() and task is not asyncio.current_task(loop=loop):
            task.cancel()


def _run_shutdown_hooks(graceful_timeout: float = 3.0):
    """Run all registered shutdown hooks with a timeout."""
    for name, fn in _shutdown_hooks:
        try:
            fn()
            logger.debug(f"Shutdown hook '{name}' completed")
        except Exception:
            logger.warning(f"Shutdown hook '{name}' failed", exc_info=True)

    # Clear hooks to avoid double-execution
    _shutdown_hooks.clear()


def _cleanup_sessions():
    """Close any lingering httpx/requests sessions found in the object graph."""
    try:
        import gc

        for obj in gc.get_objects():
            cls_name = type(obj).__name__
            if cls_name in ("Session", "Client", "AsyncClient"):
                try:
                    obj.close()
                except Exception:
                    pass
    except Exception:
        pass


# ── Convenience decorator for blocking search functions ────


def grace_period(coro):
    """Decorator for async functions that should handle interruption gracefully.

    Usage::

        @grace_period
        async def my_long_search():
            ...
    """

    async def wrapper(*args, **kwargs):
        if is_shutting_down():
            logger.info("Skipping — shutdown in progress")
            return None
        try:
            return await coro(*args, **kwargs)
        except asyncio.CancelledError:
            logger.info(f"Operation cancelled: {coro.__name__}")
            return None

    return wrapper
