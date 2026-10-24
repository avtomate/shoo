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


if __name__ == "__main__":
    unittest.main()
