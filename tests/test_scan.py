import dataclasses
import ipaddress
import tempfile
import unittest
from pathlib import Path

from helpers import ME, make_proc, table
from shoo.net import ESTABLISHED, LISTEN, NetView, Sock
from shoo.procs import CLK_TCK
from shoo.rules import Policy
from shoo.scan import run, tree_key
from shoo.state import IdleTracker

POLICY = Policy(min_age_s=3600, uid=ME)
OWN = 999_999
LO = ipaddress.ip_address("127.0.0.1")
OUTSIDE = ipaddress.ip_address("203.0.113.9")


def remember(path, proc, now, ticks=0):
    """Record a reading for proc's tree, as an earlier run would have."""
    tracker = IdleTracker(path, now=now)
    tracker.observe(tree_key(proc), ticks)
    tracker.save()


def quiet_net(socks=(), inodes=None):
    return NetView(list(socks), inodes_of=lambda pid: (inodes or {}).get(pid, set()))


def go(procs, **kw):
    kw.setdefault("net", quiet_net())
    return run(POLICY, sample=0, procs=procs, own_pid=OWN, **kw)


class Gating(unittest.TestCase):
    def test_plain_candidate_is_actionable(self):
        report = go(table(make_proc(100, "vite")))
        self.assertEqual([f.proc.pid for f in report.actionable], [100])
        self.assertEqual(report.held, {})

    def test_live_outside_connection_holds_the_tree(self):
        procs = table(make_proc(100, "vite"), make_proc(101, "esbuild", ppid=100))
        net = quiet_net([Sock((LO, 5173), (LO, 0), LISTEN, "8"),
                         Sock((LO, 5173), (OUTSIDE, 50000), ESTABLISHED, "9")], {100: {"8"}, 101: {"9"}})
        report = go(procs, net=net)
        self.assertEqual(report.actionable, [])
        self.assertIn("1 live connection", report.held[100])
        self.assertEqual(report.findings[0].connections, 1)

    def test_include_active_overrides(self):
        net = quiet_net([Sock((LO, 5173), (LO, 0), LISTEN, "8"),
                         Sock((LO, 5173), (OUTSIDE, 50000), ESTABLISHED, "9")], {100: {"8", "9"}})
        report = go(table(make_proc(100, "vite")), net=net, include_active=True)
        self.assertEqual(len(report.actionable), 1)

    def test_require_idle_needs_history(self):
        path = Path(tempfile.mkdtemp()) / "idle.json"
        proc = make_proc(100, "vite")
        procs = table(proc)

        first = go(procs, require_idle_s=7200, tracker=IdleTracker(path, now=0))
        self.assertIn("not watched long enough", first.held[100])

        remember(path, proc, now=0)
        later = go(procs, require_idle_s=7200, tracker=IdleTracker(path, now=3600))
        self.assertIn("idle 1h0m, needs 2h0m", later.held[100])

        remember(path, proc, now=3600)
        ready = go(procs, require_idle_s=7200, tracker=IdleTracker(path, now=7300))
        self.assertEqual([f.proc.pid for f in ready.actionable], [100])

    def test_tree_cpu_counts_collected_children(self):
        # A loop that spawns short-lived children: its own CPU barely moves, but the CPU of
        # children it has collected (child_ticks) shows it is busy.
        path = Path(tempfile.mkdtemp()) / "idle.json"
        proc = make_proc(100, "vite")
        remember(path, proc, now=0)
        busy = dataclasses.replace(proc, child_ticks=3600 * CLK_TCK)  # a whole core for an hour
        report = go(table(busy), require_idle_s=60, tracker=IdleTracker(path, now=3600))
        self.assertIn("idle 0m", report.held[100])

    def test_unattended_runs_hold_back_trees_inside_desktop_apps(self):
        manager = make_proc(300, "/lib/systemd/systemd --user", comm="systemd", ppid=1)
        slice_ = "/user.slice/user-1000.slice/user@1000.service/app.slice"
        # A launcher that doesn't name the scope after the PID: can't tell it from a leftover.
        unnamed = make_proc(100, "vite", ppid=300, cgroup=f"{slice_}/app-org.foo-a1b2c3.scope")
        # GNOME scope whose app (pid 50) has exited: a confirmed leftover.
        leftover = make_proc(200, "vite", ppid=300, cgroup=f"{slice_}/app-gnome-code-50.scope")
        procs = table(manager, unnamed, leftover)

        unattended = go(procs, unattended=True)
        self.assertIn("inside a desktop app", unattended.held[100])
        self.assertNotIn(200, unattended.held)

        interactive = go(procs)
        self.assertEqual({f.proc.pid for f in interactive.actionable}, {100, 200})

    def test_memory_prefers_pss(self):
        report = go(table(make_proc(100, "vite", rss_kb=500)))
        f = report.findings[0]
        self.assertEqual(f.mem_kb, f.pss_kb if f.pss_kb is not None else 500)


if __name__ == "__main__":
    unittest.main()
