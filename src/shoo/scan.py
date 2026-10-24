"""The pipeline: find candidates, measure them, and decide which trees are safe to clean.

A candidate tree (see rules.py) is *held back* rather than cleaned when:
  - something outside the tree has a live TCP connection to it (someone is using it), or
  - `require_idle_s` is set and shoo hasn't seen the whole tree idle for that long.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from .net import NetView
from .procs import CLK_TCK, Proc, pss_kb, read_proc, snapshot
from .rules import Finding, Policy, classify, explain
from .state import IdleTracker
from .util import fmt_age


@dataclass
class Report:
    findings: list[Finding]  # display order: each root followed by its children
    held: dict[int, str] = field(default_factory=dict)  # root pid -> why it won't be cleaned
    zombies: list[Proc] = field(default_factory=list)
    skipped: list[tuple[Proc, str]] = field(default_factory=list)  # only with explain=True

    @property
    def actionable(self) -> list[Finding]:
        return [f for f in self.findings if f.root not in self.held]

    @property
    def held_roots(self) -> list[Finding]:
        return [f for f in self.findings if f.root_pid is None and f.proc.pid in self.held]


def tree_key(proc: Proc) -> str:
    return f"{proc.pid}:{proc.starttime}"


def _sample_cpu(findings: list[Finding], sample: float) -> list[Finding]:
    if sample <= 0 or not findings:
        return findings
    before = {f.proc.pid: f.proc.cpu_ticks for f in findings}
    time.sleep(sample)
    out = []
    for f in findings:
        now = read_proc(f.proc.pid)
        cpu = None
        if now is not None and now.starttime == f.proc.starttime:
            cpu = (now.cpu_ticks - before[f.proc.pid]) / CLK_TCK / sample * 100
        out.append(replace(f, cpu_pct=cpu))
    return out


def run(
    policy: Policy,
    *,
    sample: float = 2.0,
    require_idle_s: float | None = None,
    include_active: bool = False,
    tracker: IdleTracker | None = None,
    explain_skipped: bool = False,
    procs: dict[int, Proc] | None = None,
    net: NetView | None = None,
    own_pid: int | None = None,
) -> Report:
    procs = snapshot() if procs is None else procs
    findings = _sample_cpu(classify(procs, policy, own_pid), sample)
    if findings and net is None:
        net = NetView()

    trees: dict[int, list[Finding]] = {}
    for f in findings:
        trees.setdefault(f.root, []).append(f)

    held: dict[int, str] = {}
    measured: dict[int, Finding] = {}
    for root_pid, members in trees.items():
        pids = {m.proc.pid for m in members}
        conns = net.outside_connections(pids)
        # Whole-tree CPU, including children that already exited and were collected, so a loop
        # that keeps spawning short-lived `sleep`s is still judged as one steady tree.
        ticks = sum(m.proc.cpu_ticks + m.proc.child_ticks for m in members)
        root = members[0]
        idle = tracker.observe(tree_key(root.proc), ticks) if tracker else None

        for m in members:
            extra = {"idle_s": idle, "connections": conns} if m is root else {}
            measured[m.proc.pid] = replace(
                m, ports=net.listening_ports(m.proc.pid), pss_kb=pss_kb(m.proc.pid), **extra
            )

        if conns and not include_active:
            held[root_pid] = f"in use: {conns} live connection{'s' if conns > 1 else ''}"
        elif require_idle_s is not None:
            if idle is None:
                held[root_pid] = "not watched long enough to know it's idle"
            elif idle < require_idle_s:
                held[root_pid] = f"idle {fmt_age(idle)}, needs {fmt_age(require_idle_s)}"

    report = Report(
        findings=[measured[f.proc.pid] for f in findings],
        held=held,
        zombies=[p for p in procs.values() if p.state == "Z"],
    )
    if explain_skipped:
        report.skipped = explain(procs, policy, {f.proc.pid for f in findings}, own_pid)
    return report
