# Changelog

All notable changes to shoo are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and shoo follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - Unreleased

First release.

### Added

- `shoo scan`: list orphaned agent and dev-tool processes, with proportional memory (PSS), CPU,
  idle time, live outside connections and listening ports. `--why` explains what was skipped;
  `--json` for scripts.
- `shoo clean`: confirm, then SIGTERM, a grace period and SIGKILL. Re-checks each process's
  start time before signalling, so a recycled PID is never hit. `--dry-run` records instead.
- Rules for MCP servers, headless browsers, Playwright drivers, JS and Python dev servers,
  language servers, agent CLIs, background tasks from finished Claude Code sessions, and
  `tail -f`-style watchers.
- Hold-back logic: trees that something outside is connected to (on a port the tree listens on)
  are never cleaned (unless `--include-active`); outbound connections don't count, and `--require-idle` only cleans trees watched idle across runs, counting the
  whole tree's CPU including children that already exited.
- `shoo schedule`: an hourly systemd user timer with cautious unattended defaults (6h minimum age,
  2h idle), and a `--dry-run` mode for watching before going live.
- `shoo log`: what was cleaned, or would have been.
- Config file for a default minimum age and protect rules.

### Safety

- `clean` and `schedule enable` refuse to run as root unless `--allow-root` is given.
- The exact process a desktop launcher started (GNOME's `app-gnome-<app>-<pid>.scope`) isn't
  treated as an orphan even when its parent is the systemd user manager; what it leaves behind
  after exiting still is.
- A `--config` file that doesn't exist, or a `protect` that isn't a list, is an error instead of
  silently running without protect rules.
- The timer pins `XDG_CONFIG_HOME` and `XDG_STATE_HOME`, so it uses the same config and log as your
  shell, and installs its units where the systemd user manager looks.
- Credentials in `Authorization:` headers and JWTs are redacted from output and the log.

[Unreleased]: https://github.com/avtomate/shoo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/avtomate/shoo/releases/tag/v0.1.0
