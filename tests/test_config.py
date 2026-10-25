import tempfile
import unittest
from pathlib import Path

from shoo.config import load


def write(text):
    path = Path(tempfile.mkdtemp()) / "config.toml"
    path.write_text(text)
    return path


class Config(unittest.TestCase):
    def test_reads_min_age_and_protect(self):
        cfg = load(write('min_age = "2h"\nprotect = ["my-app", "--port 8080"]\n'))
        self.assertEqual(cfg.min_age_s, 7200)
        self.assertEqual([p.pattern for p in cfg.protect], ["my-app", "--port 8080"])

    def test_missing_default_file_is_fine(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tempfile.mkdtemp()}):
            self.assertEqual(load().protect, ())

    def test_missing_file_you_named_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            load(Path(tempfile.mkdtemp()) / "confg.toml")

    def test_protect_must_be_a_list(self):
        # A bare string would otherwise become one pattern per character and match everything.
        with self.assertRaisesRegex(ValueError, "must be a list"):
            load(write('protect = "my-app"\n'))

    def test_unknown_keys_are_errors_with_a_hint(self):
        # A misspelled key would otherwise mean running without protect rules, silently.
        for text, hint in [('Protect = ["my-app"]\n', "did you mean 'protect'"),
                           ('protects = ["my-app"]\n', "did you mean 'protect'"),
                           ('min-age = "1d"\n', "did you mean 'min_age'"),
                           ('colour = "red"\n', "expected min_age or protect")]:
            with self.subTest(text=text), self.assertRaises(ValueError) as caught:
                load(write(text))
            self.assertIn(hint, str(caught.exception))

    def test_invalid_toml_is_a_clean_error(self):
        with self.assertRaises(ValueError):
            load(write("protect = [\n"))


if __name__ == "__main__":
    unittest.main()
