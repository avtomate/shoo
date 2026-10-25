import contextlib
import io
import unittest
from unittest import mock

from shoo import cli


class DefaultCommand(unittest.TestCase):
    def run_main(self, argv):
        scan = mock.Mock(return_value=0)
        with mock.patch.dict(cli.HANDLERS, {"scan": scan}):
            self.assertEqual(cli.main(argv), 0)
        return scan

    def test_no_arguments_scans(self):
        self.assertTrue(self.run_main([]).called)

    def test_options_without_a_command_scan(self):
        scan = self.run_main(["--min-age", "2h", "--sample", "0"])
        self.assertEqual(scan.call_args.args[0].min_age, "2h")


class Root(unittest.TestCase):
    def test_clean_and_schedule_refuse_root(self):
        for argv in (["clean", "--yes"], ["schedule", "enable"]):
            with self.subTest(argv=argv), mock.patch("os.geteuid", return_value=0), \
                    mock.patch.object(cli, "_report") as report, mock.patch.object(cli.schedule, "enable") as enable:
                self.assertEqual(cli.main(argv), 2)
                report.assert_not_called()
                enable.assert_not_called()

    def test_allow_root_overrides(self):
        empty = mock.Mock(actionable=[], held={}, skipped=[], zombies=[])
        with mock.patch("os.geteuid", return_value=0), mock.patch.object(cli, "_report", return_value=empty), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["clean", "--yes", "--allow-root"]), 0)

    def test_scan_is_allowed_as_root(self):
        scan = mock.Mock(return_value=0)
        with mock.patch("os.geteuid", return_value=0), mock.patch.dict(cli.HANDLERS, {"scan": scan}):
            self.assertEqual(cli.main(["scan"]), 0)


if __name__ == "__main__":
    unittest.main()
