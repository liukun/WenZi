"""Tests for the shared asyncio event loop singleton."""

from __future__ import annotations

import asyncio
import threading

import pytest

import wenzi.async_loop as async_loop


@pytest.fixture(autouse=True)
def _reset_loop():
    """Ensure each test gets a completely fresh loop."""
    # Clean up any loop left over from a previous test
    async_loop.shutdown_sync(timeout=2)

    yield

    # Clean up the loop created during this test
    async_loop.shutdown_sync(timeout=2)


class TestGetLoop:
    def test_returns_running_loop(self):
        loop = async_loop.get_loop()
        assert loop is not None
        assert loop.is_running()

    def test_idempotent(self):
        loop1 = async_loop.get_loop()
        loop2 = async_loop.get_loop()
        assert loop1 is loop2

    def test_runs_on_daemon_thread(self):
        async_loop.get_loop()
        assert async_loop._thread is not None
        assert async_loop._thread.daemon is True
        assert async_loop._thread.name == "wenzi-asyncio"

    def test_concurrent_get_loop(self):
        """Multiple threads calling get_loop simultaneously should get the same loop."""
        loops: list[asyncio.AbstractEventLoop] = []
        lock = threading.Lock()

        def grab():
            loop = async_loop.get_loop()
            with lock:
                loops.append(loop)

        threads = [threading.Thread(target=grab) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(loops) == 10
        assert all(lp is loops[0] for lp in loops)


class TestSubmit:
    def test_submit_coroutine(self):
        async def add(a, b):
            return a + b

        future = async_loop.submit(add(2, 3))
        assert future.result(timeout=2) == 5

    def test_submit_from_multiple_threads(self):
        results: list[int] = []

        async def append(val):
            results.append(val)
            return val

        threads = []
        for i in range(10):
            t = threading.Thread(
                target=lambda v=i: async_loop.submit(append(v)).result(timeout=5)
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert sorted(results) == list(range(10))

    def test_submit_exception_propagates(self):
        async def fail():
            raise ValueError("boom")

        future = async_loop.submit(fail())
        with pytest.raises(ValueError, match="boom"):
            future.result(timeout=2)


class TestShutdown:
    def test_shutdown_cancels_pending_tasks(self):
        cancelled = threading.Event()

        async def long_task():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async_loop.submit(long_task())

        # Give the task time to reach sleep
        async def _noop():
            await asyncio.sleep(0.05)
        async_loop.submit(_noop()).result(timeout=2)

        async_loop.shutdown_sync(timeout=2)

        assert cancelled.wait(timeout=2)

    def test_shutdown_stops_loop(self):
        loop = async_loop.get_loop()
        assert loop.is_running()

        async_loop.shutdown_sync(timeout=2)

        assert not loop.is_running()
        assert async_loop._loop is None
        assert async_loop._thread is None

    def test_shutdown_is_idempotent(self):
        async_loop.get_loop()
        async_loop.shutdown_sync(timeout=2)
        # Second call should be a no-op
        async_loop.shutdown_sync(timeout=2)

    def test_get_loop_works_after_shutdown(self):
        loop1 = async_loop.get_loop()
        async_loop.shutdown_sync(timeout=2)

        loop2 = async_loop.get_loop()
        assert loop2 is not loop1
        assert loop2.is_running()


class TestCallLater:
    def test_fires_callback(self):
        fired = threading.Event()
        async_loop.call_later(0.01, fired.set)
        assert fired.wait(timeout=2)

    def test_cancel_prevents_callback(self):
        fired = threading.Event()
        handle = async_loop.call_later(0.1, fired.set)
        handle.cancel()
        assert not fired.wait(timeout=0.3)

    def test_cancel_is_idempotent(self):
        handle = async_loop.call_later(10, lambda: None)
        handle.cancel()
        handle.cancel()  # should not raise

    def test_passes_args(self):
        results = []
        done = threading.Event()

        def cb(a, b):
            results.append(a + b)
            done.set()

        async_loop.call_later(0.01, cb, 3, 4)
        assert done.wait(timeout=2)
        assert results == [7]

    def test_returns_timer_handle(self):
        handle = async_loop.call_later(10, lambda: None)
        assert isinstance(handle, async_loop.TimerHandle)
        handle.cancel()
