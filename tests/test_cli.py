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


class Prompt(unittest.TestCase):
    def test_ctrl_d_or_ctrl_c_at_the_prompt_aborts_cleanly(self):
        report = mock.Mock(actionable=[mock.Mock()], held={}, skipped=[], zombies=[])
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error.__name__), mock.patch.object(cli, "_report", return_value=report), \
                    mock.patch.object(cli, "_print_report"), mock.patch("sys.stdin.isatty", return_value=True), \
                    mock.patch("builtins.input", side_effect=error), mock.patch.object(cli, "clean") as kill, \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(cli.main(["clean"]), 1)
                kill.assert_not_called()
                self.assertIn("Aborted.", out.getvalue())


class Interrupted(unittest.TestCase):
    def test_interrupted_clean_is_logged_and_exits_130(self):
        target = mock.Mock()
        target.proc.pid = 4242
        report = mock.Mock(actionable=[target], held={}, skipped=[], zombies=[])
        with mock.patch.object(cli, "_report", return_value=report), mock.patch.object(cli, "_print_report"), \
                mock.patch.object(cli, "clean", return_value={4242: "interrupted"}), \
                mock.patch.object(cli, "_log_record", return_value={"pid": 4242}), \
                mock.patch.object(cli.state, "append_log") as log, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["clean", "--yes"]), 130)
        log.assert_called_once_with([{"pid": 4242}])


class Root(unittest.TestCase):
    def test_clean_and_schedule_refuse_root(self):
        for argv in (["clean", "--yes"], ["schedule", "enable"]):
            with self.subTest(argv=argv), mock.patch("os.geteuid", return_value=0), \
                    mock.patch.object(cli, "_report") as report, mock.patch.object(cli.schedule, "enable") as enable, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(cli.main(argv), 2)
                report.assert_not_called()
                enable.assert_not_called()
                self.assertIn("refusing to run as root", err.getvalue())

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
