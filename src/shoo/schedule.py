"""Run `shoo clean` automatically with a systemd user timer.

Everything lives in the user's own systemd (no root, nothing system-wide):
    ~/.config/systemd/user/shoo.service   what to run
    ~/.config/systemd/user/shoo.timer     when to run it
(or under $XDG_CONFIG_HOME, if your systemd user manager has it set). Each run's output goes to the
journal (`journalctl --user -u shoo.service`), and every process it cleans, or would have cleaned in
--dry-run, is recorded for `shoo log`.

The service pins XDG_CONFIG_HOME and XDG_STATE_HOME to what your shell resolved at enable time, so
the timer reads the same config (your protect rules) and writes the same log you see, even when
those variables are set only in your shell profile.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .util import parse_duration, xdg_dir

NAME = "shoo"
DEFAULT_EVERY = "1h"
DEFAULT_MIN_AGE = "6h"  # more conservative than the interactive default: nobody is watching
DEFAULT_REQUIRE_IDLE = "2h"  # and the whole tree must have sat idle across runs this long
MIN_EVERY_S = 300


NO_SYSTEMD = (
    "`shoo schedule` needs systemd user services, which aren't available here. You can still run "
    "`shoo clean --yes --min-age 6h --require-idle 2h` from cron."
)


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["systemctl", "--user", *args], text=True, capture_output=True)
    except FileNotFoundError:
        raise ValueError(NO_SYSTEMD) from None


def unit_dir(strict: bool = True) -> Path:
    """Where the systemd user manager actually looks for your units.

    Asks the manager for its search path rather than guessing from environment variables. With
    strict=False (disable, status) an unreachable manager falls back to the standard location, so
    the files can still be found and removed.
    """
    try:
        r = _systemctl("show", "-p", "UnitPath", "--value")
        if r.returncode != 0:
            raise ValueError(f"couldn't reach your systemd user manager: {r.stderr.strip() or 'unknown error'}")
    except ValueError:
        if strict:
            raise
        return xdg_dir("config") / "systemd" / "user"
    for entry in r.stdout.split():
        if entry.endswith("/systemd/user") and not entry.startswith(("/run/", "/etc/", "/usr/")):
            return Path(entry)
    return Path.home() / ".config" / "systemd" / "user"


def _quote(path: str) -> str:
    return f'"{path}"' if " " in path else path


def render(
    every_s: int, min_age_s: int, require_idle_s: int, python: str, pythonpath: str,
    dry_run: bool = False, config_home: str | None = None, state_home: str | None = None,
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
Environment=XDG_CONFIG_HOME={_quote(config_home or str(xdg_dir("config")))}
Environment=XDG_STATE_HOME={_quote(state_home or str(xdg_dir("state")))}
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

    d = unit_dir()  # also confirms the user manager is reachable before anything is written
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


def _try_systemctl(*args: str) -> None:
    try:
        _systemctl(*args)
    except ValueError:
        pass


def disable() -> int:
    d = unit_dir(strict=False)
    _try_systemctl("disable", "--now", f"{NAME}.timer")
    for suffix in ("service", "timer"):
        (d / f"{NAME}.{suffix}").unlink(missing_ok=True)
    _try_systemctl("daemon-reload")
    print("Disabled and removed the shoo timer.")
    return 0


def mode() -> str | None:
    """'live', 'dry-run', or None if not scheduled."""
    try:
        service = (unit_dir(strict=False) / f"{NAME}.service").read_text()
    except FileNotFoundError:
        return None
    return "dry-run" if "--dry-run" in service else "live"


def status() -> int:
    current = mode()
    if current is None:
        print("Not scheduled. Turn it on with: shoo schedule enable  (or --dry-run to watch first)")
        return 0
    print(f"Mode: {current}" + ("  (recording only, killing nothing)" if current == "dry-run" else ""))
    try:
        print(_systemctl("list-timers", f"{NAME}.timer", "--no-pager").stdout.strip())
    except ValueError:
        print("(couldn't reach the systemd user manager to show the next run)")
    print("\nRecent activity: shoo log")
    print(f"Full run output:  journalctl --user -u {NAME}.service")
    return 0
