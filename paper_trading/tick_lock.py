"""Exclusive cross-process lock for the append-only paper/data writers.

Cycle 27 found the same workspace mounted in more than one container (separate
PID namespaces), each able to run its own copy of a daemon. The writers are
idempotent (they resume from the last recorded row), but two of them running at
the same instant could both read the same "last row" and append it twice. Taking
this POSIX lock (fcntl.lockf — honoured across processes on the same kernel and
over NFS) around the whole read-last -> append section makes concurrent ticks run
one after the other, so the second finds nothing new to do.
"""
import fcntl
import os
from contextlib import contextmanager

LOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


@contextmanager
def exclusive(name):
    os.makedirs(LOCK_DIR, exist_ok=True)
    with open(os.path.join(LOCK_DIR, f"{name}.lock"), "a") as f:
        fcntl.lockf(f, fcntl.LOCK_EX)          # blocks until the other tick is done
        try:
            yield
        finally:
            fcntl.lockf(f, fcntl.LOCK_UN)
