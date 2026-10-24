"""TCP sockets: what a process listens on, and whether anything outside its tree is talking to it.

A live connection from outside the tree (a browser tab, an SSH tunnel, another program) means
someone is still using the process, so it is not abandoned. Connections between processes in the
same tree (a dev server and its own worker) don't count.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass

from .procs import PROC

LISTEN, ESTABLISHED = "0A", "01"

Addr = tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, int]


@dataclass(frozen=True)
class Sock:
    local: Addr
    remote: Addr
    state: str
    inode: str


def parse_addr(text: str) -> Addr:
    """'0100007F:1F90' -> (127.0.0.1, 8080). /proc/net stores each 32-bit word little-endian."""
    host, port = text.split(":")
    raw = bytes.fromhex(host)
    raw = b"".join(raw[i : i + 4][::-1] for i in range(0, len(raw), 4))
    ip = ipaddress.ip_address(raw)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip, int(port, 16)


def read_sockets() -> list[Sock]:
    socks = []
    for table in ("tcp", "tcp6"):
        try:
            lines = (PROC / "net" / table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) > 9:
                socks.append(Sock(parse_addr(f[1]), parse_addr(f[2]), f[3], f[9]))
    return socks


def fd_inodes(pid: int) -> set[str]:
    """Socket inodes held open by a process (empty if unreadable)."""
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
        pass
    return inodes


class NetView:
    """One snapshot of the TCP tables, queried per process tree."""

    def __init__(self, socks: list[Sock] | None = None, inodes_of=fd_inodes):
        self.socks = read_sockets() if socks is None else socks
        self._inodes_of = inodes_of
        self._by_ends = {(s.local, s.remote): s for s in self.socks if s.state == ESTABLISHED}

    def listening_ports(self, pid: int) -> tuple[int, ...]:
        mine = self._inodes_of(pid)
        return tuple(sorted({s.local[1] for s in self.socks if s.state == LISTEN and s.inode in mine}))

    def outside_connections(self, pids: set[int]) -> int:
        """Established connections between this tree and anything not in it."""
        tree = set().union(*(self._inodes_of(pid) for pid in pids)) if pids else set()
        count = 0
        for s in self.socks:
            if s.state != ESTABLISHED or s.inode not in tree:
                continue
            if not s.remote[0].is_loopback:
                count += 1
                continue
            peer = self._by_ends.get((s.remote, s.local))
            # An unknown peer (other user, another namespace, half-closed) is assumed to be a user.
            if peer is None or peer.inode not in tree:
                count += 1
        return count
