import multiprocessing as mp
import pytest


def _mp_available() -> bool:
    try:
        ctx = mp.get_context("spawn")
        lock = ctx.Lock()
        lock.acquire()
        lock.release()
    except Exception:
        return False
    return True


def pytest_collection_modifyitems(config, items):
    if _mp_available():
        return
    skip = pytest.mark.skip(reason="multiprocessing semaphores unavailable")
    for item in items:
        nodeid = item.nodeid
        if "test_deferred.py" in nodeid or "test_picklable.py" in nodeid:
            item.add_marker(skip)
