import unittest

from shoo.schedule import render


class Units(unittest.TestCase):
    def test_service_runs_clean_unattended_with_a_conservative_age(self):
        service, _ = render(3600, 21600, "/usr/bin/python3", "/opt/shoo/src")
        self.assertIn("ExecStart=/usr/bin/python3 -m shoo clean --yes --sample 0 --min-age 21600", service)
        self.assertIn("Environment=PYTHONPATH=/opt/shoo/src", service)
        self.assertIn("Type=oneshot", service)
        self.assertIn("Nice=19", service)

    def test_timer_repeats_and_is_wanted_by_timers_target(self):
        _, timer = render(3600, 21600, "/usr/bin/python3", "/opt/shoo/src")
        self.assertIn("OnUnitActiveSec=3600s", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_paths_with_spaces_are_quoted(self):
        service, _ = render(3600, 21600, "/usr/bin/python3", "/my files/src")
        self.assertIn('Environment=PYTHONPATH="/my files/src"', service)


if __name__ == "__main__":
    unittest.main()
