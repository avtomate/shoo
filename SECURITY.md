# Security policy

shoo terminates processes, so its safety guarantees matter as much as its features. Thank you for
helping keep it trustworthy.

## Supported versions

shoo is pre-1.0. Security fixes go into the latest release only.

## Reporting a vulnerability

**Please don't open a public issue.** Report privately through this repository's **Security** tab
→ **Report a vulnerability** (GitHub private vulnerability reporting). Include what you ran, what
happened, and what you expected, plus steps to reproduce if you have them.

This is a solo-maintained project. I aim to acknowledge reports within 7 days, and to agree on a
fix and disclosure timeline with you before anything is published. You'll be credited in the
advisory unless you'd rather not be.

## What counts

Anything that breaks one of the guarantees in the README, for example:

- shoo signals a process it shouldn't be able to: another user's, a systemd service or container,
  `tmux`/`screen`/`sshd`, itself or its ancestors, or a process whose PID was recycled.
- An unattended run (`--yes`, the timer) cleans a tree that should have been held back: one with
  live outside connections, or one not yet watched idle for `--require-idle`.
- shoo reads `/proc/<pid>/environ`, or a credential in a command line survives redaction into the
  output or the log.
- shoo's state files (`~/.local/state/shoo`) or timer units can be used to run code or escalate
  privileges, or are created readable by other users.

A rule that is merely too broad (it flags something it shouldn't, but `scan` shows it and `clean`
asks first) is a normal bug: please open a regular "Wrong match" issue for those.
