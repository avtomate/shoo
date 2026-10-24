import unittest

from shoo.procs import parse_stat
from shoo.util import fmt_age, fmt_kb, parse_duration, redact


class Durations(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_duration("90m"), 5400)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("45"), 45)

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            parse_duration("soon")

    def test_formatting(self):
        self.assertEqual(fmt_age(5400), "1h30m")
        self.assertEqual(fmt_age(90000), "1d1h")
        self.assertEqual(fmt_kb(2048), "2M")
        self.assertEqual(fmt_kb(3 * 1024 * 1024), "3.0G")


class Redaction(unittest.TestCase):
    def test_flags_env_assignments_urls_and_token_shapes(self):
        cases = {
            "tool --api-key abc123 --port 80": "tool --api-key *** --port 80",
            "tool --token=abc123": "tool --token=***",
            "env GITHUB_TOKEN=ghp_abcdefgh12345 node x.js": "env GITHUB_TOKEN=*** node x.js",
            "psql postgres://bob:hunter2@db/app": "psql postgres://***@db/app",
            "curl -H sk-abcdefghijkl": "curl -H ***",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact(raw), expected)
                self.assertNotIn("abc123", redact(raw))

    def test_leaves_normal_commands_alone(self):
        self.assertEqual(redact("vite --port 5173"), "vite --port 5173")


class ProcStat(unittest.TestCase):
    def test_comm_with_spaces_and_parens(self):
        # proc(5) field n sits at index n-3 after the comm: state=3, ppid=4, tty_nr=7,
        # utime=14, stime=15, starttime=22.
        fields = ["0"] * 22
        fields[0], fields[1], fields[4] = "S", "42", "34816"
        fields[11], fields[12], fields[19] = "5", "6", "9999"
        line = "123 (my (weird) app) " + " ".join(fields)
        got = parse_stat(line)
        self.assertEqual(got["comm"], "my (weird) app")
        self.assertEqual((got["state"], got["ppid"], got["tty_nr"]), ("S", 42, 34816))
        self.assertEqual(got["cpu_ticks"], 11)
        self.assertEqual(got["starttime"], 9999)


if __name__ == "__main__":
    unittest.main()
