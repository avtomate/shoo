import tempfile
import unittest
from pathlib import Path

from shoo.procs import CLK_TCK
from shoo.state import IdleTracker, append_log, read_log


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

    def test_corrupt_state_starts_fresh(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json")
        self.assertIsNone(self.observe_and_save(0, 0))


class Log(unittest.TestCase):
    def test_round_trip_and_tail(self):
        path = Path(tempfile.mkdtemp()) / "log.jsonl"
        append_log([{"n": i} for i in range(5)], path)
        self.assertEqual([e["n"] for e in read_log(2, path)], [3, 4])

    def test_missing_log_is_empty(self):
        self.assertEqual(read_log(5, Path(tempfile.mkdtemp()) / "nope.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
