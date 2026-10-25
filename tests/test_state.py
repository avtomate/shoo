import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shoo import state
from shoo.procs import CLK_TCK
from shoo.state import IdleTracker, already_recorded, append_log, read_log


class Idle(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "idle.json"

    def tracker(self, now):
        return IdleTracker(self.path, now=now)

    def observe_and_save(self, now, ticks, key="7:70"):
        t = self.tracker(now)
        idle = t.observe(key, ticks)
        t.save()
        return idle

    def test_first_sighting_is_unknown(self):
        self.assertIsNone(self.observe_and_save(1000, 0))

    def test_idle_accumulates_across_quiet_runs(self):
        self.observe_and_save(0, 100)
        self.assertEqual(self.observe_and_save(3600, 100), 3600)
        # A trickle of CPU (well under 1%) still counts as idle.
        self.assertEqual(self.observe_and_save(7200, 100 + 2 * CLK_TCK), 7200)

    def test_activity_resets_the_clock(self):
        self.observe_and_save(0, 0)
        self.observe_and_save(3600, 0)
        busy = 3600 * CLK_TCK // 10  # 10% of a core for an hour
        self.assertEqual(self.observe_and_save(7200, busy), 0)
        self.assertEqual(self.observe_and_save(10800, busy), 3600)

    def test_readings_too_close_together_are_ignored(self):
        self.observe_and_save(0, 0)
        self.observe_and_save(3600, 0)
        self.assertEqual(self.observe_and_save(3610, 10**9), 3610)  # 10s later: not judged

    def test_old_entries_are_forgotten(self):
        self.observe_and_save(0, 0, key="old")
        self.observe_and_save(3 * 86400, 0, key="new")
        self.assertNotIn("old", self.tracker(3 * 86400).data)

    def test_state_of_the_wrong_shape_is_discarded_not_crashed_on(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for body in ["[]", "42", '{"7:70": {"ticks": 1}}', '{"7:70": "x"}',
                     '{"7:70": {"ticks": "a", "seen": 1, "idle_since": null}}']:
            with self.subTest(body=body):
                self.path.write_text(body)
                self.assertIsNone(self.observe_and_save(0, 0))  # starts fresh, rewrites a valid file
                self.assertEqual(self.observe_and_save(3600, 0), 3600)

    def test_valid_entries_survive_next_to_bad_ones(self):
        self.observe_and_save(0, 0)
        data = json.loads(self.path.read_text())
        data["junk"] = []
        self.path.write_text(json.dumps(data))
        self.assertEqual(self.observe_and_save(3600, 0), 3600)

    def test_corrupt_state_starts_fresh(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json")
        self.assertIsNone(self.observe_and_save(0, 0))


def entry(pid, action="would-clean", start=1):
    return {"ts": 1, "action": action, "pid": pid, "start": start, "kind": "k", "mem_kb": 1, "command": "c"}


class Log(unittest.TestCase):
    def test_round_trip_and_tail(self):
        path = Path(tempfile.mkdtemp()) / "log.jsonl"
        append_log([entry(i) for i in range(5)], path)
        self.assertEqual([e["pid"] for e in read_log(2, path)], [3, 4])

    def test_malformed_log_lines_are_skipped(self):
        path = Path(tempfile.mkdtemp()) / "log.jsonl"
        path.write_text("123\n[1]\n{\"ts\": 1}\nnot json\n" + json.dumps(entry(9)) + "\n")
        self.assertEqual([e["pid"] for e in read_log(10, path)], [9])

    def test_a_lingering_process_is_recorded_once_in_dry_run(self):
        path = Path(tempfile.mkdtemp()) / "log.jsonl"
        append_log([entry(5, start=50), entry(6, action="terminated", start=60)], path)
        self.assertEqual(already_recorded(path), {(5, 50)})  # only would-clean counts
        # A new process that reuses pid 5 has a different start time and is recorded again.
        self.assertNotIn((5, 99), already_recorded(path))

    def test_trimming_keeps_the_newest_lines(self):
        path = Path(tempfile.mkdtemp()) / "log.jsonl"
        with mock.patch.object(state, "LOG_MAX_LINES", 5), mock.patch.object(state, "LOG_KEEP_LINES", 2):
            append_log([entry(i) for i in range(7)], path)
        self.assertEqual([e["pid"] for e in read_log(10, path)], [5, 6])

    def test_missing_log_is_empty(self):
        self.assertEqual(read_log(5, Path(tempfile.mkdtemp()) / "nope.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
