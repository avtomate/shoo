# Contributing to shoo

Thanks for helping. The most valuable contributions are reports of what shoo gets wrong on real
machines: things it flagged that it shouldn't have, and leftovers it missed.

Please follow the [code of conduct](CODE_OF_CONDUCT.md). For security problems, see
[SECURITY.md](SECURITY.md) instead of opening an issue.

## Reporting a wrong match or a missed leftover

Use the issue templates. The two things that help most:

- the command line (from `shoo scan --why` or `ps -eo pid,ppid,args`), with anything private
  redacted: tokens, hostnames, personal paths;
- what started the process (which agent, tool or editor), and whether it was really abandoned.

## Development

shoo has no dependencies; you only need Python 3.11+ on Linux.

```bash
git clone https://github.com/avtomate/shoo && cd shoo
PYTHONPATH=src python3 -m shoo --why                         # run from the checkout
PYTHONPATH=src:tests python3 -m unittest discover -s tests   # tests
uvx ruff check src tests                                     # lint (or: pipx run ruff ...)
```

CI runs the tests on Python 3.11 to 3.13, plus the linter, on every push and pull request.

## Adding or changing a rule

Rules live in `src/shoo/rules.py`. Because a rule decides what gets killed, the bar is:

1. **Match the program, not the path.** Rules see the program and its first few arguments with
   directories stripped (see `_head`). Use `full=True` only for a signature that can't appear by
   accident, like `run-driver`.
2. **Test both sides.** In `tests/test_rules.py`, add the command lines the rule should match *and*
   a realistic lookalike it must not match, such as a project directory or flag with the same word.
3. **Prefer narrow.** A missed leftover costs some memory; a wrong match can kill someone's work.

## Changes that touch safety

Anything in `cleaner.py`, `protected_reason`, `orphan_reason` or the hold-back logic in `scan.py`
needs a test showing the protection still holds. Safety checks are never weakened to make a rule
work; make the rule narrower instead.

## Pull requests

- Keep each PR to one change, with tests, and update `CHANGELOG.md` under *Unreleased*.
- Describe how you tested it, ideally including `shoo scan --why` output from a real machine.

## Releasing (maintainers)

1. Move the *Unreleased* changelog entries under a new version heading with today's date.
2. Bump `__version__` in `src/shoo/__init__.py` (the package version is read from there).
3. Commit, then tag and publish a GitHub release named `vX.Y.Z`. The release workflow builds
   the package and publishes it to PyPI through trusted publishing.
