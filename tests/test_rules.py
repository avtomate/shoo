import re
import unittest

from helpers import ME, make_proc, table
from shoo.rules import Policy, classify, explain, match_rule

POLICY = Policy(min_age_s=3600, uid=ME)
OWN = 999_999  # a pid that isn't in any test table


def kinds(findings):
    return {f.proc.pid: f.rule for f in findings}


class RuleMatching(unittest.TestCase):
    def test_known_agent_and_dev_tools_match(self):
        cases = {
            "npx -y @modelcontextprotocol/server-filesystem /tmp": "mcp-server",
            "uvx mcp-server-fetch": "mcp-server",
            "node /srv/app/node_modules/some-mcp/dist/index.js": "mcp-server",
            "/usr/bin/chromium --headless=new --remote-debugging-port=9222": "headless-browser",
            "node /x/playwright/driver/package/cli.js run-driver": "browser-automation",
            "node /x/node_modules/.bin/vite --port 5173": "node-dev-server",
            "next dev -p 3000": "node-dev-server",
            "npm run typecheck": "node-launcher",
            "uvicorn app:app --reload": "python-dev-server",
            "python3 -m http.server 8000": "python-dev-server",
            "node /x/typescript/lib/tsserver.js": "language-server",
            "tail -f /var/log/app.log": "watcher",
            "/home/u/.local/bin/claude --resume": "agent-cli",
        }
        for cmd, expected in cases.items():
            with self.subTest(cmd=cmd):
                rule = match_rule(make_proc(10, cmd))
                self.assertIsNotNone(rule)
                self.assertEqual(rule.name, expected)

    def test_ordinary_programs_do_not_match(self):
        for cmd in ["postgres: checkpointer", "nginx: worker process", "/usr/sbin/cron -f",
                    "python3 train.py --epochs 50", "bash", "mcpelauncher"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(match_rule(make_proc(10, cmd)))

    def test_claude_code_background_task_matches_but_other_shells_do_not(self):
        task = ("/bin/bash -c source /home/u/.claude/shell-snapshots/snapshot-bash-17925-jb42d4.sh "
                "2>/dev/null || true && eval 'until [ -f done ]; do sleep 5; done'")
        self.assertEqual(match_rule(make_proc(10, task, comm="bash")).name, "agent-task")
        for cmd in ["/bin/bash -c ./backup.sh", "bash", "/bin/sh -c cat snapshot-notes.sh"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(match_rule(make_proc(10, cmd, comm=cmd.split()[0].rsplit("/")[-1])))

    def test_words_in_paths_and_flags_do_not_count(self):
        # Regression: a bash wrapper whose `cd` target was a project directory named *-mcp was
        # flagged as an MCP server.
        wrapper = ("/bin/bash -c eval 'cd /srv/code/my-mcp && until [ -f out.txt ]; do sleep 5; done'")
        self.assertIsNone(match_rule(make_proc(10, wrapper, comm="bash")))
        for cmd in ["node /srv/code/my-mcp/evals/run-eval.mjs",
                    "node run-eval.mjs --mcp-url http://localhost",
                    "python train.py --data /data/vite-project/set",
                    "grep -r claude /srv/code",
                    "cat /var/log/chromium --headless.txt"]:
            with self.subTest(cmd=cmd):
                self.assertIsNone(match_rule(make_proc(10, cmd)))


class Classification(unittest.TestCase):
    def test_orphaned_old_dev_server_is_a_candidate(self):
        procs = table(make_proc(100, "vite --port 5173"))
        self.assertEqual(kinds(classify(procs, POLICY, OWN)), {100: "node-dev-server"})

    def test_process_with_a_live_parent_is_left_alone(self):
        procs = table(make_proc(50, "supervisor-app", ppid=1), make_proc(100, "vite", ppid=50))
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_systemd_user_subreaper_counts_as_orphaned(self):
        procs = table(
            make_proc(300, "/lib/systemd/systemd --user", comm="systemd", ppid=1),
            make_proc(100, "vite", ppid=300),
        )
        self.assertEqual(kinds(classify(procs, POLICY, OWN)), {100: "node-dev-server"})

    def test_dev_server_launched_through_an_orphaned_shell_is_found(self):
        procs = table(
            make_proc(50, "/bin/bash -c cd app && vite", ppid=1, comm="bash"),
            make_proc(100, "vite", ppid=50),
        )
        self.assertEqual(kinds(classify(procs, POLICY, OWN)), {100: "node-dev-server"})

    def test_shell_wrapped_server_in_a_live_terminal_is_left_alone(self):
        procs = table(
            make_proc(50, "bash", ppid=1, comm="bash", tty_nr=4 << 8),
            make_proc(100, "vite", ppid=50, tty_nr=4 << 8),
        )
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_young_process_is_left_alone(self):
        procs = table(make_proc(100, "vite", age_s=60))
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_other_users_processes_are_left_alone(self):
        procs = table(make_proc(100, "vite", uid=ME + 1))
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_managed_services_and_containers_are_left_alone(self):
        for cg in ["/system.slice/docker-abc.scope",
                   "/user.slice/user-1000.slice/user@1000.service/app.slice/dev.service",
                   "/kubepods/burstable/pod1/abc"]:
            with self.subTest(cgroup=cg):
                procs = table(make_proc(100, "vite", cgroup=cg))
                self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_live_terminal_protects_a_process(self):
        # tty_nr for /dev/pts/0 is major 136, minor 0; this test box has pts/0 or not,
        # so use a non-pts tty (major 4) which is always treated as alive.
        procs = table(make_proc(100, "vite", tty_nr=4 << 8))
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_user_protect_rule_wins(self):
        policy = Policy(min_age_s=3600, uid=ME, protect=(re.compile("5173"),))
        procs = table(make_proc(100, "vite --port 5173"))
        self.assertEqual(classify(procs, policy, OWN), [])

    def test_never_targets_itself_or_its_ancestors(self):
        procs = table(make_proc(100, "vite", ppid=1), make_proc(200, "npx shoo", ppid=100))
        self.assertEqual(classify(procs, POLICY, own_pid=200), [])

    def test_zombies_are_ignored(self):
        procs = table(make_proc(100, "vite", state="Z"))
        self.assertEqual(classify(procs, POLICY, OWN), [])

    def test_children_are_swept_up_after_their_root(self):
        procs = table(
            make_proc(100, "vite", rss_kb=500),
            make_proc(101, "esbuild --service", ppid=100),
            make_proc(102, "node worker.js", ppid=101),
            make_proc(103, "sshd", ppid=100, comm="sshd"),  # protected, must be skipped
        )
        found = classify(procs, POLICY, OWN)
        self.assertEqual([f.proc.pid for f in found], [100, 101, 102])
        self.assertEqual(found[1].root_pid, 100)
        self.assertEqual(found[2].rule, "child")

    def test_largest_candidates_come_first(self):
        procs = table(make_proc(100, "vite", rss_kb=10), make_proc(200, "vite", rss_kb=999))
        self.assertEqual([f.proc.pid for f in classify(procs, POLICY, OWN)], [200, 100])


class Explain(unittest.TestCase):
    def test_reasons(self):
        procs = table(
            make_proc(50, "supervisor-app", ppid=1),
            make_proc(100, "vite", ppid=50),                       # live parent
            make_proc(200, "vite", age_s=60),                      # too young
            make_proc(300, "python3 my_job.py"),                   # orphan, no rule
            make_proc(400, "vite", cgroup="/system.slice/x.service"),  # protected
            make_proc(500, "vite"),                                # a candidate
            make_proc(600, "vite", uid=ME + 1),                    # someone else's: not listed
        )
        found = {f.proc.pid for f in classify(procs, POLICY, OWN)}
        why = dict((p.pid, r) for p, r in explain(procs, POLICY, found, OWN))
        self.assertIn("parent (supervisor-app 50) is alive", why[100])
        self.assertIn("too young", why[200])
        self.assertEqual(why[300], "orphaned, but no rule matches")
        self.assertTrue(why[400].startswith("protected"))
        self.assertNotIn(500, why)
        self.assertNotIn(600, why)
        self.assertEqual(why[50], "orphaned, but no rule matches")


if __name__ == "__main__":
    unittest.main()
