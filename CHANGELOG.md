# Changelog

All notable changes to shoo are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and shoo follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-25

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
  are never cleaned (unless `--include-active`), nor are trees connected out to one of your own
  running programs; other outbound connections, like API keep-alives, don't count, and `--require-idle` only cleans trees watched idle across runs, counting the
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
- Unattended runs hold back trees in a desktop app's scope unless the app that owned it has
  exited, since some launchers don't name the scope after the app's PID.
- Ctrl-C at any point during `clean` stops sending signals, reports every process (including ones
  never reached) and logs what was already signalled; nothing is escalated to SIGKILL.
- Rules identify a process by its program and script file names only. A directory argument such
  as `--root /home/me/mcp` or `python app.py /srv/vite` can no longer make an unrelated process
  match a rule.
- Anything inside a systemd service's cgroup tree is protected, including nested sub-cgroups.
- An unknown key in `config.toml` (`Protect`, `min-age`) is an error with a hint, not silently
  ignored.
- A corrupt or foreign `idle.json` or `log.jsonl` is discarded or skipped instead of crashing
  every run, and a log write failure never hides what `clean` did.
- A dry-run records each lingering process once, not on every hourly run.
- Redaction covers attached short options (`mysql -pSECRET`) and no longer swallows the argument
  after a boolean flag such as `--no-auth`.
- Credentials in `Authorization:`, `x-api-key:`, `Cookie:` and similar headers, and JWTs, are
  redacted from output and the log.

[Unreleased]: https://github.com/avtomate/shoo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/avtomate/shoo/releases/tag/v0.1.0
