"""TCP sockets: what a process listens on, and whether anything outside its tree is talking to it.

A tree is in use when something outside it is connected to it:
  - a connection *into* a port it listens on (a browser tab, an SSH tunnel), or
  - a loopback connection *out* to one of your own live processes (a debug adapter or language
    server attached to a running editor).
Other outbound connections don't count: an abandoned agent can hold a keep-alive to an API, or a
dev server a pool to a system database, forever. Nor do connections within the tree.
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
    uid: int = -1


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
                socks.append(Sock(parse_addr(f[1]), parse_addr(f[2]), f[3], f[9], int(f[7])))
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
        self._inode_cache: dict[int, set[str]] = {}
        self._listen_port = {s.inode: s.local[1] for s in self.socks if s.state == LISTEN}
        self._by_ends = {(s.local, s.remote): s for s in self.socks if s.state == ESTABLISHED}

    def _inodes(self, pid: int) -> set[str]:
        if pid not in self._inode_cache:
            self._inode_cache[pid] = self._inodes_of(pid)
        return self._inode_cache[pid]

    def listening_ports(self, pid: int) -> tuple[int, ...]:
        return tuple(sorted({self._listen_port[i] for i in self._inodes(pid) if i in self._listen_port}))

    def outside_connections(self, pids: set[int]) -> int:
        """Live connections that show something outside this tree is using it (see module doc)."""
        tree = set().union(*(self._inodes(pid) for pid in pids)) if pids else set()
        serving = {self._listen_port[i] for i in tree if i in self._listen_port}
        count = 0
        for s in self.socks:
            if s.state != ESTABLISHED or s.inode not in tree:
                continue
            peer = self._by_ends.get((s.remote, s.local)) if s.remote[0].is_loopback else None
            if s.local[1] in serving:
                # Inbound. An unknown peer (another user, namespace, half-closed) counts as a user.
                if not s.remote[0].is_loopback or peer is None or peer.inode not in tree:
                    count += 1
            elif peer is not None and peer.inode not in tree and peer.uid == s.uid:
                count += 1  # outbound to one of your own processes, e.g. an editor
        return count
