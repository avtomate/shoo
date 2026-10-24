## What and why

<!-- One change per PR. Link the issue if there is one. -->

## How it was tested

<!-- Tests added or changed. For rule changes, ideally `shoo scan --why` output from a real machine
     (redact anything private). -->

## Checklist

- [ ] Tests cover the change (for rules: what should match *and* a lookalike that mustn't)
- [ ] `PYTHONPATH=src:tests python3 -m unittest discover -s tests` passes
- [ ] `uvx ruff check src tests` passes
- [ ] `CHANGELOG.md` updated under *Unreleased*
