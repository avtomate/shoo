"""Run `shoo clean` automatically with a systemd user timer.

Everything lives in the user's own systemd (no root, nothing system-wide):
    ~/.config/systemd/user/shoo.service   what to run
    ~/.config/systemd/user/shoo.timer     when to run it
Each run's output goes to the journal (`journalctl --user -u shoo.service`), and every process it
cleans, or would have cleaned in --dry-run, is recorded for `shoo log`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .util import parse_duration

NAME = "shoo"
DEFAULT_EVERY = "1h"
DEFAULT_MIN_AGE = "6h"  # more conservative than the interactive default: nobody is watching
DEFAULT_REQUIRE_IDLE = "2h"  # and the whole tree must have sat idle across runs this long
MIN_EVERY_S = 300


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "systemd" / "user"


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def render(
    every_s: int, min_age_s: int, require_idle_s: int, python: str, pythonpath: str,
    dry_run: bool = False,
) -> tuple[str, str]:
    """Return (service_unit, timer_unit) text."""
    flags = f"--yes --sample 0 --min-age {min_age_s} --require-idle {require_idle_s}"
    if dry_run:
        flags += " --dry-run"
    service = f"""[Unit]
Description=shoo: clean up orphaned agent and dev-tool processes{" (dry run)" if dry_run else ""}

[Service]
Type=oneshot
Environment=PYTHONPATH={_quote(pythonpath)}
ExecStart={_quote(python)} -m shoo clean {flags}
Nice=19
IOSchedulingClass=idle
"""
    timer = f"""[Unit]
Description=Run shoo regularly

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


def enable(
    every: str = DEFAULT_EVERY,
    min_age: str = DEFAULT_MIN_AGE,
    require_idle: str = DEFAULT_REQUIRE_IDLE,
    dry_run: bool = False,
) -> int:
    every_s, min_age_s = int(parse_duration(every)), int(parse_duration(min_age))
    require_idle_s = int(parse_duration(require_idle))
    if every_s < MIN_EVERY_S:
        raise ValueError("--every must be at least 5m")
    # Resolves both for an installed package and for a plain checkout run with PYTHONPATH=src.
    pythonpath = str(Path(__file__).resolve().parent.parent)
    service, timer = render(every_s, min_age_s, require_idle_s, sys.executable, pythonpath, dry_run)

    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.service").write_text(service)
    (d / f"{NAME}.timer").write_text(timer)

    for step in (("daemon-reload",), ("enable", "--now", f"{NAME}.timer")):
        r = _systemctl(*step)
        if r.returncode != 0:
            print(f"systemctl --user {' '.join(step)} failed:\n{r.stderr.strip()}", file=sys.stderr)
            return 1

    if dry_run:
        print(f"Enabled in dry-run mode: every {every}, shoo records what it *would* clean, and "
              "kills nothing.")
        print("  review it:        shoo log")
        print("  go live:          shoo schedule enable")
    else:
        print(f"Enabled: every {every}, shoo cleans leftovers older than {min_age} that have sat "
              f"idle for {require_idle}.")
        print("  see what it did:  shoo log")
    print("  turn it off:      shoo schedule disable")
    if _linger_enabled() is False:
        print("\nWarning: lingering is off, so the timer stops when you log out. Fix with:\n"
              "  loginctl enable-linger")
    return 0


def disable() -> int:
    _systemctl("disable", "--now", f"{NAME}.timer")
    for suffix in ("service", "timer"):
        (unit_dir() / f"{NAME}.{suffix}").unlink(missing_ok=True)
    _systemctl("daemon-reload")
    print("Disabled and removed the shoo timer.")
    return 0


def mode() -> str | None:
    """'live', 'dry-run', or None if not scheduled."""
    try:
        service = (unit_dir() / f"{NAME}.service").read_text()
    except FileNotFoundError:
        return None
    return "dry-run" if "--dry-run" in service else "live"


def status() -> int:
    current = mode()
    if current is None:
        print("Not scheduled. Turn it on with: shoo schedule enable  (or --dry-run to watch first)")
        return 0
    print(f"Mode: {current}" + ("  (recording only, killing nothing)" if current == "dry-run" else ""))
    print(_systemctl("list-timers", f"{NAME}.timer", "--no-pager").stdout.strip())
    print("\nRecent activity: shoo log")
    print(f"Full run output:  journalctl --user -u {NAME}.service")
    return 0
