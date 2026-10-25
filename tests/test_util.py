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

    def test_authorization_headers_and_jwts(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        for raw in [f"curl -H 'Authorization: Bearer {jwt}' https://api.example.com",
                    "curl -H Authorization: Basic dXNlcjpodW50ZXIy https://x",
                    f"node client.js --session {jwt}",
                    "http GET x Proxy-Authorization:token-abcdef123456"]:
            with self.subTest(raw=raw):
                out = redact(raw)
                for secret in ("eyJ", "dXNlcjpodW50ZXIy", "token-abcdef123456"):
                    self.assertNotIn(secret, out)

    def test_other_credential_headers(self):
        for raw in ['curl -H "x-api-key: abcd1234secretvalue" https://x',
                    "curl -H 'Cookie: session=abcd1234secretvalue' https://x",
                    "curl -H X-Auth-Token:abcd1234secretvalue https://x"]:
            with self.subTest(raw=raw):
                out = redact(raw)
                self.assertNotIn("abcd1234secretvalue", out)
                self.assertIn("https://x", out)

    def test_redaction_keeps_the_rest_of_the_command(self):
        self.assertEqual(redact("curl -H Authorization:token-abc https://example.com/path"),
                         "curl -H Authorization: *** https://example.com/path")
        self.assertEqual(redact("python -m http.server --bind 0.0.0.0 basic configuration_file"),
                         "python -m http.server --bind 0.0.0.0 basic configuration_file")

    def test_leaves_normal_commands_alone(self):
        self.assertEqual(redact("vite --port 5173"), "vite --port 5173")


class ProcStat(unittest.TestCase):
    def test_comm_with_spaces_and_parens(self):
        # proc(5) field n sits at index n-3 after the comm: state=3, ppid=4, tty_nr=7,
        # utime=14, stime=15, starttime=22.
        fields = ["0"] * 22
        fields[0], fields[1], fields[4] = "S", "42", "34816"
        fields[11], fields[12], fields[19] = "5", "6", "9999"
        fields[13], fields[14] = "30", "4"  # cutime, cstime
        line = "123 (my (weird) app) " + " ".join(fields)
        got = parse_stat(line)
        self.assertEqual(got["comm"], "my (weird) app")
        self.assertEqual((got["state"], got["ppid"], got["tty_nr"]), ("S", 42, 34816))
        self.assertEqual(got["cpu_ticks"], 11)
        self.assertEqual(got["child_ticks"], 34)
        self.assertEqual(got["starttime"], 9999)


if __name__ == "__main__":
    unittest.main()
