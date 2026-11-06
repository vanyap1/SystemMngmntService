"""Background watch loop for a running test: emergency stop button, fixture lid, supply fault, ...

An asyncio loop in a background thread calls every check periodically while the steps of ts.run() execute.
A check is a plain function or an `async def`; it **raises an exception to abort the test**. The exception is
delivered to the main thread at once (SIGINT, so even time.sleep(), a serial read or an operator dialog is
interrupted) as testStrategy.AbortTest: ts.run() logs it as an ERROR step, skips the remaining steps and runs
finalize(). The watch is stopped before finalize(), so finalization is never interrupted.

    from testStrategy import TestStrategy
    from testWatch import TestWatch, EmergencyStop

    ts = TestStrategy()
    watch = TestWatch()

    def estop():                                   # raise = abort the test
        if estop_line.get_value() == 1:
            raise EmergencyStop("button pressed")

    watch.add("Emergency stop", estop, interval=0.05)
    watch.require("Fixture lid closed", lambda: lid_line.get_value() == 0, "lid opened")   # False = abort

    ts.run(steps, finalize, watch=watch)

Without ts.run() use it as a context manager: `with watch: ...` (an abort then raises AbortTest there).
A real Ctrl+C / Stop of the Tests page keeps working as before (KeyboardInterrupt).
"""
import asyncio
import inspect
import signal
import threading
import time

from testStrategy import AbortTest


class EmergencyStop(Exception):
    """Convenience exception for a pressed emergency stop button (any exception aborts the test)."""


class WatchAbort(AbortTest):
    """The AbortTest raised in the main thread when a watched check fails."""
    def __init__(self, name, error):
        message = str(error) or type(error).__name__
        if not isinstance(error, (EmergencyStop, AssertionError)):
            message = f"{type(error).__name__}: {message}"
        super().__init__(name, message)
        self.error = error


class TestWatch:
    __test__ = False                          # not a unittest/pytest class despite the name

    def __init__(self, interval: float = 0.1):
        self.interval = interval
        self._checks = []                     # [(name, fn, interval)]
        self._thread = None
        self._loop = None
        self._stop = None
        self._abort = None                    # WatchAbort waiting to be raised in the main thread
        self._delivered = False
        self._armed = False                   # while True a pending abort is raised by the SIGINT handler
        self._prev_handler = None
        self._main = None

    # ── configuration ──
    def add(self, name: str, check, interval: float = None) -> "TestWatch":
        """Call `check()` every `interval` s (default: the watch interval); an exception aborts the test."""
        self._checks.append((name, check, interval or self.interval))
        return self

    def require(self, name: str, condition, message: str = "condition lost", interval: float = None) -> "TestWatch":
        """Abort the test when `condition()` returns a false value."""
        def check():
            ok = condition()
            if inspect.isawaitable(ok):
                return _require_async(ok, message)
            if not ok:
                raise AssertionError(message)
        return self.add(name, check, interval)

    @property
    def error(self):
        """The WatchAbort of the check that failed, or None."""
        return self._abort

    # ── lifecycle (ts.run() calls these) ──
    def start(self) -> "TestWatch":
        if self._thread:
            return self
        self._abort, self._delivered = None, False
        self._main = threading.main_thread()
        if threading.current_thread() is self._main:
            self._prev_handler = signal.signal(signal.SIGINT, self._on_sigint)
        self._armed = True
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, args=(ready,), name="test-watch", daemon=True)
        self._thread.start()
        ready.wait(2)
        return self

    def stop(self) -> None:
        """Stop the checks; an abort that has not reached the main thread yet is dropped."""
        self._armed = False
        if self._loop and self._stop:
            try:
                self._loop.call_soon_threadsafe(self._stop.set)
            except RuntimeError:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(2)
        self._thread = None

    def close(self) -> None:
        """Stop and restore the previous Ctrl+C handler."""
        self.stop()
        if self._prev_handler is not None and threading.current_thread() is self._main:
            signal.signal(signal.SIGINT, self._prev_handler)
        self._prev_handler = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # ── internals ──
    def _on_sigint(self, signum, frame):
        if self._abort is not None and not self._delivered:
            if self._armed:
                self._delivered = True
                raise self._abort
            return                            # abort arrived after stop(): finalization goes on
        prev = self._prev_handler
        if callable(prev):
            return prev(signum, frame)
        if prev == signal.SIG_IGN:
            return
        raise KeyboardInterrupt

    def _run_loop(self, ready):
        loop = asyncio.new_event_loop()
        self._loop = loop
        try:
            loop.run_until_complete(self._main_task(ready))
        finally:
            loop.close()
            self._loop = None

    async def _main_task(self, ready):
        self._stop = asyncio.Event()
        ready.set()
        tasks = [asyncio.ensure_future(self._poll(name, fn, iv)) for name, fn, iv in self._checks]
        await self._stop.wait()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _poll(self, name, fn, interval):
        while not self._stop.is_set():
            try:
                r = fn()
                if inspect.isawaitable(r):
                    await r
            except asyncio.CancelledError:
                raise
            except BaseException as e:        # noqa: B902 — any failure of a check aborts the test
                self._fail(name, e)
                return
            try:
                await asyncio.wait_for(self._stop.wait(), interval)
            except asyncio.TimeoutError:
                pass

    def _fail(self, name, error):
        if self._abort is not None or not self._armed:
            return
        self._abort = WatchAbort(name, error)
        self._stop.set()
        # A real signal to the main thread: interrupts sleep(), blocking reads and operator dialogs.
        try:
            signal.pthread_kill(self._main.ident, signal.SIGINT)
        except (AttributeError, ProcessLookupError, OSError):
            import _thread
            _thread.interrupt_main()


async def _require_async(awaitable, message):
    if not await awaitable:
        raise AssertionError(message)


def file_flag(path: str, message: str = "emergency stop"):
    """Check that raises EmergencyStop while the file `path` exists — a stand-in for a button on a bench
    without hardware (`touch <path>` = press, `rm <path>` = release)."""
    import os

    def check():
        if os.path.exists(path):
            raise EmergencyStop(message)
    return check


if __name__ == "__main__":
    # Self-test: the "button" is pressed 1 s after start, while the main thread sleeps.
    from testStrategy import TestStrategy
    ts = TestStrategy()
    t0 = time.time()

    def button():
        if time.time() - t0 > 1:
            raise EmergencyStop("button pressed")

    w = TestWatch().add("Emergency stop", button, interval=0.05)

    def steps():
        ts.logResult("Long step", True, "started")
        time.sleep(10)
        ts.logResult("Never reached", True)

    ts.run(steps, lambda: ts.logResult("Power off", True, "OK"), watch=w)
    print(f"finished after {time.time() - t0:.1f} s")
