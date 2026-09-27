#!/usr/bin/env python3
"""Tests for the shared daemon machinery (paper_trading/daemon_lib.sh) and the
two thin daemons on top of it (daemon_4h.sh, daemon_paper.sh).

Exercises the REAL library via a throwaway dummy daemon (DAEMON_NAME=selftest)
so it never touches the production collect_4h / paper daemons and never hits the
live API: the dummy tick just echoes and sleeps a long time. Verifies detached
launch (reparent to PID 1), idempotent start/ensure, crash self-heal, and stop.

Plain asserts (no pytest): run with `python3 tests/test_daemons.py`.
Skips gracefully if not on Linux/bash (no /proc, no setsid).
"""
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PT = os.path.join(ROOT, "paper_trading")
LOGS = os.path.join(ROOT, "logs")

checks = []


def check(name, cond):
    checks.append((name, cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def sh(script, cmd):
    return subprocess.run(["bash", script, cmd], cwd=ROOT,
                          capture_output=True, text=True)


# ---- static: every daemon script is syntactically valid bash ----
for f in ("daemon_lib.sh", "daemon_4h.sh", "daemon_paper.sh"):
    p = os.path.join(PT, f)
    r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
    check(f"{f} passes `bash -n`", r.returncode == 0)

# Skip the live-lifecycle part where the OS primitives aren't available.
if not (os.path.isdir("/proc") and shutil.which("setsid") and shutil.which("bash")):
    print("  [SKIP] lifecycle test (needs Linux /proc + setsid)")
    failed = [n for n, ok in checks if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
          f"({len(checks) - len(failed)}/{len(checks)})")
    sys.exit(1 if failed else 0)

# ---- dynamic: full lifecycle on a throwaway dummy daemon ----
NAME = "selftest"
dummy = os.path.join(PT, "_selftest_daemon.sh")
pidfile = os.path.join(LOGS, f"{NAME}_daemon.pid")
logfile = os.path.join(LOGS, f"{NAME}_daemon.log")

DUMMY = r'''#!/usr/bin/env bash
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
DAEMON_NAME="selftest"
DAEMON_DESC="throwaway self-test daemon"
source "$(dirname "$SELF")/daemon_lib.sh"
daemon_tick() { echo "selftest tick"; }
daemon_next_sleep() { echo 3600; }
daemon_main "$@"
'''

try:
    with open(dummy, "w") as f:
        f.write(DUMMY)
    os.chmod(dummy, 0o755)

    # start -> running, detached (ppid==1), pidfile present
    sh(dummy, "start")
    time.sleep(1.2)
    alive = os.path.exists(pidfile) and \
        subprocess.run(["bash", dummy, "status"], cwd=ROOT,
                       capture_output=True, text=True).stdout.startswith("STATUS: RUNNING")
    check("dummy daemon starts and reports RUNNING", alive)
    pid = int(open(pidfile).read().strip())
    ppid = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                          capture_output=True, text=True).stdout.strip()
    check("daemon is detached (reparented to PID 1)", ppid == "1")

    # ensure while running -> idempotent no-op (pid unchanged)
    out = sh(dummy, "ensure").stdout
    check("ensure while running is a no-op", "already running" in out and
          int(open(pidfile).read().strip()) == pid)

    # crash -> not running
    os.kill(pid, 9)
    time.sleep(1.0)
    st = sh(dummy, "status").stdout
    check("status after crash is NOT running", st.startswith("STATUS: NOT"))

    # ensure -> self-heals (new pid, still detached)
    sh(dummy, "ensure")
    time.sleep(1.2)
    st2 = sh(dummy, "status").stdout
    new_pid = int(open(pidfile).read().strip()) if os.path.exists(pidfile) else -1
    check("ensure self-heals after crash", st2.startswith("STATUS: RUNNING")
          and new_pid not in (-1, pid))

    # stop -> not running, pidfile removed
    sh(dummy, "stop")
    time.sleep(0.5)
    check("stop halts daemon and clears pidfile",
          sh(dummy, "status").stdout.startswith("STATUS: NOT")
          and not os.path.exists(pidfile))
finally:
    # cleanup: ensure no dummy left running, remove dummy artifacts
    try:
        if os.path.exists(pidfile):
            try:
                os.kill(int(open(pidfile).read().strip()), 9)
            except (ProcessLookupError, ValueError):
                pass
    finally:
        for p in (dummy, pidfile, logfile):
            if os.path.exists(p):
                os.remove(p)

# ---- summary ----
failed = [n for n, ok in checks if not ok]
print(f"\n{'ALL PASS' if not failed else 'FAILURES: ' + '; '.join(failed)} "
      f"({len(checks) - len(failed)}/{len(checks)})")
sys.exit(1 if failed else 0)
