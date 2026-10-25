import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shoo import schedule
from shoo.schedule import render


class Units(unittest.TestCase):
    def test_service_runs_clean_unattended_with_a_conservative_age(self):
        service, _ = render(3600, 21600, 7200, "/usr/bin/python3", "/opt/shoo/src")
        self.assertIn(
            "ExecStart=/usr/bin/python3 -m shoo clean --yes --sample 0 --min-age 21600 --require-idle 7200\n",
            service,
        )
        self.assertIn("Environment=PYTHONPATH=/opt/shoo/src", service)
        self.assertIn("Type=oneshot", service)
        self.assertIn("Nice=19", service)

    def test_timer_repeats_and_is_wanted_by_timers_target(self):
        _, timer = render(3600, 21600, 7200, "/usr/bin/python3", "/opt/shoo/src")
        self.assertIn("OnUnitActiveSec=3600s", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_dry_run_kills_nothing(self):
        service, _ = render(3600, 21600, 7200, "/usr/bin/python3", "/opt/shoo/src", dry_run=True)
        self.assertIn("--require-idle 7200 --dry-run", service)

    def test_service_pins_config_and_state_dirs(self):
        # So the timer reads the same protect rules and writes the same log as your shell.
        service, _ = render(3600, 21600, 7200, "/usr/bin/python3", "/opt/shoo/src",
                            config_home="/home/u/dotfiles/config", state_home="/home/u/.local/state")
        self.assertIn("Environment=XDG_CONFIG_HOME=/home/u/dotfiles/config\n", service)
        self.assertIn("Environment=XDG_STATE_HOME=/home/u/.local/state\n", service)

    def test_missing_systemd_is_a_clean_error(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("systemctl")):
            with self.assertRaisesRegex(ValueError, "needs systemd"):
                schedule.enable()

    def test_unit_dir_is_where_the_user_manager_looks(self):
        unit_path = ("/home/u/.config/systemd/user.control /run/user/1000/systemd/transient "
                     "/srv/cfg/systemd/user /etc/systemd/user /home/u/.local/share/systemd/user")
        out = mock.Mock(returncode=0, stdout=unit_path + "\n")
        with mock.patch.object(schedule, "_systemctl", return_value=out), \
                mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": "/somewhere/else"}):
            self.assertEqual(str(schedule.unit_dir()), "/srv/cfg/systemd/user")

    def test_disable_and_status_work_without_a_reachable_manager(self):
        config_home = Path(tempfile.mkdtemp())
        units = config_home / "systemd" / "user"
        units.mkdir(parents=True)
        (units / "shoo.service").write_text("ExecStart=python -m shoo clean --dry-run\n")
        (units / "shoo.timer").write_text("")
        no_manager = ValueError("couldn't reach your systemd user manager")
        with mock.patch.object(schedule, "_systemctl", side_effect=no_manager), \
                mock.patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(schedule.mode(), "dry-run")
            self.assertEqual(schedule.status(), 0)
            self.assertEqual(schedule.disable(), 0)
        self.assertEqual(list(units.iterdir()), [])

    def test_paths_with_spaces_are_quoted(self):
        service, _ = render(3600, 21600, 7200, "/usr/bin/python3", "/my files/src")
        self.assertIn('Environment=PYTHONPATH="/my files/src"', service)


if __name__ == "__main__":
    unittest.main()
