"""Terminate processes politely, then firmly, without ever hitting a recycled PID."""

from __future__ import annotations

import os
import signal
import time

from .procs import Proc, read_proc
from .rules import Finding


def still_same(proc: Proc) -> bool:
    """True only if this exact process (pid + start time) is still running."""
    now = read_proc(proc.pid)
    return now is not None and now.starttime == proc.starttime and now.state != "Z"


def _send(proc: Proc, sig: int) -> str | None:
    """Signal the process if it is still the one we scanned. Returns an outcome on failure."""
    if not still_same(proc):
        return "gone"
    try:
        os.kill(proc.pid, sig)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        return "denied"
    return None


def reap(
    findings: list[Finding], grace: float = 5.0, poll: float = 0.1
) -> dict[int, str]:
    """SIGTERM everything, wait up to `grace` seconds, SIGKILL what remains.

    Returns pid -> 'terminated' | 'killed' | 'gone' | 'denied'.
    """
    results: dict[int, str] = {}
    pending: dict[int, Proc] = {}

    for f in findings:
        outcome = _send(f.proc, signal.SIGTERM)
        if outcome:
            results[f.proc.pid] = outcome
        else:
            pending[f.proc.pid] = f.proc

    deadline = time.monotonic() + grace
    while pending and time.monotonic() < deadline:
        for pid in [pid for pid, p in pending.items() if not still_same(p)]:
            results[pid] = "terminated"
            del pending[pid]
        if pending:
            time.sleep(poll)

    for pid, proc in pending.items():
        outcome = _send(proc, signal.SIGKILL)
        results[pid] = outcome or "killed"
    return results
