"""What shoo remembers between runs: how long each leftover has been idle, and what it did.

Stored under $XDG_STATE_HOME/shoo (default ~/.local/state/shoo), readable only by you:
    idle.json    CPU readings per process tree, to tell "idle for hours" from "busy"
    log.jsonl    one line per process cleaned (or, in --dry-run, that would have been)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .procs import CLK_TCK
from .util import xdg_dir

IDLE_CPU_PCT = 1.0  # a tree averaging below this between runs counts as idle
MIN_INTERVAL_S = 60  # readings closer together than this are too noisy to judge
FORGET_AFTER_S = 2 * 86400
LOG_MAX_LINES, LOG_KEEP_LINES = 5000, 2000
LOG_FIELDS = frozenset({"ts", "action", "pid", "kind", "mem_kb", "command"})


def state_dir() -> Path:
    return xdg_dir("state") / "shoo"


def _ensure_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)


def _number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _valid_reading(v) -> bool:
    return (
        isinstance(v, dict)
        and _number(v.get("ticks"))
        and _number(v.get("seen"))
        and (v.get("idle_since") is None or _number(v["idle_since"]))
    )


class IdleTracker:
    """Remembers CPU readings per tree (keyed by root pid + start time) across runs."""

    def __init__(self, path: Path | None = None, now: float | None = None):
        self.path = path or state_dir() / "idle.json"
        self.now = time.time() if now is None else now
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            raw = {}
        # Anything of the wrong shape is dropped, not trusted: a corrupt file must never stop
        # every future run (including the timer's) with a traceback.
        raw = raw if isinstance(raw, dict) else {}
        self.data: dict[str, dict] = {k: v for k, v in raw.items() if _valid_reading(v)}

    def observe(self, key: str, ticks: int) -> float | None:
        """Record a reading. Returns seconds idle, or None if we haven't watched it long enough."""
        prev = self.data.get(key)
        if prev is None:
            self.data[key] = {"ticks": ticks, "seen": self.now, "idle_since": None}
            return None
        elapsed = self.now - prev["seen"]
        if elapsed >= MIN_INTERVAL_S:
            cpu_pct = max(0, ticks - prev["ticks"]) / CLK_TCK / elapsed * 100
            if cpu_pct <= IDLE_CPU_PCT:
                idle_since = prev["idle_since"] if prev["idle_since"] is not None else prev["seen"]
            else:
                idle_since = self.now
            prev = self.data[key] = {"ticks": ticks, "seen": self.now, "idle_since": idle_since}
        return None if prev["idle_since"] is None else self.now - prev["idle_since"]

    def save(self) -> None:
        self.data = {k: v for k, v in self.data.items() if self.now - v["seen"] < FORGET_AFTER_S}
        _ensure_dir(self.path.parent)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data))
        os.replace(tmp, self.path)


def log_path() -> Path:
    return state_dir() / "log.jsonl"


def append_log(records: list[dict], path: Path | None = None) -> None:
    if not records:
        return
    path = path or log_path()
    _ensure_dir(path.parent)
    with open(path, "a") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    lines = path.read_text().splitlines()
    if len(lines) > LOG_MAX_LINES:
        tmp = path.with_suffix(".tmp")
        tmp.write_text("\n".join(lines[-LOG_KEEP_LINES:]) + "\n")
        os.replace(tmp, path)


def read_log(n: int, path: Path | None = None) -> list[dict]:
    try:
        lines = (path or log_path()).read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and LOG_FIELDS <= entry.keys():
            out.append(entry)
    return out


def already_recorded(path: Path | None = None) -> set[tuple[int, int]]:
    """(pid, start time) of every process already logged as 'would-clean', so an hourly dry run
    records a lingering process once instead of every hour."""
    return {(e["pid"], e.get("start")) for e in read_log(LOG_MAX_LINES, path) if e["action"] == "would-clean"}
