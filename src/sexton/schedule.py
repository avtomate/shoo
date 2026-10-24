"""Run `sexton clean` automatically with a systemd user timer.

Everything lives in the user's own systemd (no root, nothing system-wide):
    ~/.config/systemd/user/sexton.service   what to run
    ~/.config/systemd/user/sexton.timer     when to run it
Output goes to the journal: `journalctl --user -u sexton.service`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .util import parse_duration

NAME = "sexton"
DEFAULT_EVERY = "1h"
DEFAULT_MIN_AGE = "6h"  # more conservative than the interactive default: nobody is watching
MIN_EVERY_S = 300


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user"


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def render(every_s: int, min_age_s: int, python: str, pythonpath: str) -> tuple[str, str]:
    """Return (service_unit, timer_unit) text."""
    service = f"""[Unit]
Description=sexton: clean up orphaned agent and dev-tool processes

[Service]
Type=oneshot
Environment=PYTHONPATH={_quote(pythonpath)}
ExecStart={_quote(python)} -m sexton clean --yes --sample 0 --min-age {min_age_s}
Nice=19
IOSchedulingClass=idle
"""
    timer = f"""[Unit]
Description=Run sexton regularly

[Timer]
OnBootSec=10min
OnUnitActiveSec={every_s}s

[Install]
WantedBy=timers.target
"""
    return service, timer


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], text=True, capture_output=True)


def _linger_enabled() -> bool | None:
    try:
        out = subprocess.run(
            ["loginctl", "show-user", str(os.getuid()), "-p", "Linger", "--value"],
            text=True, capture_output=True,
        )
    except FileNotFoundError:
        return None
    return out.stdout.strip() == "yes" if out.returncode == 0 else None


def enable(every: str = DEFAULT_EVERY, min_age: str = DEFAULT_MIN_AGE) -> int:
    every_s, min_age_s = int(parse_duration(every)), int(parse_duration(min_age))
    if every_s < MIN_EVERY_S:
        raise ValueError("--every must be at least 5m")
    # Resolves both for an installed package and for a plain checkout run with PYTHONPATH=src.
    pythonpath = str(Path(__file__).resolve().parent.parent)
    service, timer = render(every_s, min_age_s, sys.executable, pythonpath)

    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.service").write_text(service)
    (d / f"{NAME}.timer").write_text(timer)

    for step in (("daemon-reload",), ("enable", "--now", f"{NAME}.timer")):
        r = _systemctl(*step)
        if r.returncode != 0:
            print(f"systemctl --user {' '.join(step)} failed:\n{r.stderr.strip()}", file=sys.stderr)
            return 1

    print(f"Enabled: sexton will clean every {every}, touching only processes older than {min_age}.")
    print(f"  see what it did:  journalctl --user -u {NAME}.service")
    print("  turn it off:      sexton schedule disable")
    if _linger_enabled() is False:
        print("\nWarning: lingering is off, so the timer stops when you log out. Fix with:\n"
              "  loginctl enable-linger")
    return 0


def disable() -> int:
    _systemctl("disable", "--now", f"{NAME}.timer")
    for suffix in ("service", "timer"):
        (unit_dir() / f"{NAME}.{suffix}").unlink(missing_ok=True)
    _systemctl("daemon-reload")
    print("Disabled and removed the sexton timer.")
    return 0


def status() -> int:
    timer = unit_dir() / f"{NAME}.timer"
    if not timer.exists():
        print("Not scheduled. Turn it on with: sexton schedule enable")
        return 0
    print(_systemctl("list-timers", f"{NAME}.timer", "--no-pager").stdout.strip())
    print("\nRecent runs:")
    log = subprocess.run(
        ["journalctl", "--user", "-u", f"{NAME}.service", "-n", "15", "--no-pager", "-o", "cat"],
        text=True, capture_output=True,
    )
    print(log.stdout.strip() or "(none yet)")
    return 0
