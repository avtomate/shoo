"""Read process facts straight from /proc.

Deliberately never opens /proc/<pid>/environ: environment variables are where
secrets live, and nothing shoo does needs them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROC = Path("/proc")
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
PTS_MAJOR = 136


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    uid: int
    state: str
    session: int
    tty_nr: int
    starttime: int  # clock ticks since boot; with pid, uniquely identifies a process
    cpu_ticks: int  # utime + stime
    rss_kb: int
    comm: str
    cmdline: str
    cgroup: str
    age_s: float


def parse_stat(text: str) -> dict:
    """Parse /proc/<pid>/stat. comm may contain spaces and parens, so split on the last ')'."""
    rparen = text.rindex(")")
    comm = text[text.index("(") + 1 : rparen]
    rest = text[rparen + 2 :].split()
    # Field n of proc(5) lives at rest[n - 3].
    return {
        "comm": comm,
        "state": rest[0],
        "ppid": int(rest[1]),
        "session": int(rest[3]),
        "tty_nr": int(rest[4]),
        "cpu_ticks": int(rest[11]) + int(rest[12]),
        "starttime": int(rest[19]),
    }


def uptime_s() -> float:
    return float((PROC / "uptime").read_text().split()[0])


def read_proc(pid: int, uptime: float | None = None) -> Proc | None:
    """Snapshot one process, or None if it vanished or can't be read."""
    base = PROC / str(pid)
    try:
        stat = parse_stat((base / "stat").read_text())
        uid = base.stat().st_uid
        rss_pages = int((base / "statm").read_text().split()[1])
        raw = (base / "cmdline").read_bytes()
        cgroup_text = (base / "cgroup").read_text()
    except (OSError, ValueError, IndexError):
        return None

    cmdline = " ".join(raw.decode(errors="replace").split("\0")).strip() or f"[{stat['comm']}]"
    cgroup = next(
        (line[3:] for line in cgroup_text.splitlines() if line.startswith("0::")),
        cgroup_text.splitlines()[-1].split(":", 2)[-1] if cgroup_text.strip() else "",
    )
    if uptime is None:
        uptime = uptime_s()
    return Proc(
        pid=pid,
        ppid=stat["ppid"],
        uid=uid,
        state=stat["state"],
        session=stat["session"],
        tty_nr=stat["tty_nr"],
        starttime=stat["starttime"],
        cpu_ticks=stat["cpu_ticks"],
        rss_kb=rss_pages * PAGE_KB,
        comm=stat["comm"],
        cmdline=cmdline,
        cgroup=cgroup,
        age_s=max(0.0, uptime - stat["starttime"] / CLK_TCK),
    )


def snapshot() -> dict[int, Proc]:
    """Every readable process, keyed by pid."""
    up = uptime_s()
    procs = {}
    for entry in os.scandir(PROC):
        if entry.name.isdigit():
            p = read_proc(int(entry.name), up)
            if p is not None:
                procs[p.pid] = p
    return procs


def tty_state(tty_nr: int) -> str:
    """'none' (no controlling terminal), 'alive', or 'gone' (a pty that no longer exists)."""
    if tty_nr == 0:
        return "none"
    major = (tty_nr >> 8) & 0xFFF
    minor = (tty_nr & 0xFF) | ((tty_nr >> 12) & 0xFFF00)
    if major == PTS_MAJOR:
        return "alive" if Path(f"/dev/pts/{minor}").exists() else "gone"
    return "alive"


def listening_ports(pid: int) -> tuple[int, ...]:
    """TCP ports this process is listening on (empty if unknown or unreadable)."""
    inodes = set()
    try:
        for fd in os.scandir(PROC / str(pid) / "fd"):
            try:
                link = os.readlink(fd.path)
            except OSError:
                continue
            if link.startswith("socket:["):
                inodes.add(link[8:-1])
    except OSError:
        return ()
    if not inodes:
        return ()

    ports = set()
    for table in ("tcp", "tcp6"):
        try:
            lines = (PROC / "net" / table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) > 9 and f[3] == "0A" and f[9] in inodes:
                ports.add(int(f[1].rsplit(":", 1)[1], 16))
    return tuple(sorted(ports))
