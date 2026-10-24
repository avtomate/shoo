# sexton

Find and clean up **orphaned agent and dev-tool processes** that are quietly eating your RAM.

If you run coding agents on a Linux box (or a VPS), you've probably seen it: MCP servers, headless
browsers, dev servers and language servers that an agent spawned, then abandoned. Nothing is using
them, nothing will ever use them again, and they hold hundreds of megabytes each.

`sexton` finds those and, when you say so, terminates them. It is a **janitor, not a sniper**: it
only touches processes it can show are abandoned, and it changes nothing unless you ask.

```
$ sexton
    PID    AGE    RSS  CPU%  KIND             PORTS      COMMAND
 412907  3d4h   612M     0  node-dev-server  5173       node .../node_modules/.bin/vite --port 5173
 412930  3d4h    88M     0    └ child                      esbuild --service=0.21.5 --ping
 388120  1d9h   430M     0  headless-browser -          chromium --headless=new --remote-debugging-port=9222
 301554  6d2h   171M     0  mcp-server       -          npx -y @modelcontextprotocol/server-filesystem /srv

4 processes, about 1.3G reclaimable. Run `sexton clean` to clean them up.
```

## "Zombie" processes vs. what you actually have

A true zombie (`Z` in `ps`) has already exited. It uses **no memory and no CPU**; it's just a leftover
entry waiting for its parent to collect it. You can't kill one, and it goes away when the parent does.

What eats your RAM is **orphaned live processes**: still running, but their parent (the agent session,
the shell, the terminal) is gone. That is what `sexton` looks for. (If zombies exist, `sexton` mentions
them and explains why there is nothing to kill.)

## Install and run

Requires Linux and Python 3.11+. No dependencies.

```bash
git clone <this repo> && cd sexton
python3 -m pip install .        # or: pipx install .
sexton                          # same as `sexton scan`; read-only
sexton clean                    # asks first
```

Or without installing: `PYTHONPATH=src python3 -m sexton`.

## Commands

| Command | What it does |
| --- | --- |
| `sexton` / `sexton scan` | List reclaimable processes. Changes nothing. `--json` for scripts. |
| `sexton clean` | Show the list, ask for confirmation, then SIGTERM, wait, SIGKILL stragglers. `-y` skips the prompt; `--grace SECS` sets the wait. |
| `sexton schedule enable` | Clean automatically in the background (see below). Also `disable` and `status`. |
| `sexton rules` | Print what it looks for. |

Options for `scan` and `clean`: `--min-age 2h` (default `1h`), `--protect REGEX` (repeatable),
`--sample SECS` (CPU measurement window, `0` to skip), `--config PATH`.

## Run it automatically

```bash
sexton schedule enable                           # hourly, only processes older than 6h
sexton schedule enable --every 30m --min-age 12h
sexton schedule status                           # next run + what it did
sexton schedule disable
```

This installs a systemd *user* timer (no root, nothing system-wide). The unattended default
`--min-age` is 6h, more cautious than the interactive 1h, since nobody is watching. Every run is
logged: `journalctl --user -u sexton.service`. On a server, make sure lingering is on
(`loginctl enable-linger`) or the timer stops when you log out; `schedule enable` warns if it's off.

## When is a process a candidate?

**All** of these must be true:

1. It matches a known agent or dev-tool rule (`sexton rules`): MCP servers, headless browsers,
   Playwright drivers, JS and Python dev servers, language servers, agent CLIs, `tail -f`-style watchers.
   Matching looks at the program and its first few arguments, never at directory names, so a project
   called `my-mcp` doesn't make everything inside it look like an MCP server.
2. It is **orphaned**: its parent is gone (re-parented to init or your `systemd --user`) and it is not
   attached to a live terminal. A process launched through a shell wrapper (`bash -c "npm run dev"`)
   counts as orphaned if the wrapper is.
3. It has been running longer than `--min-age`.
4. It is **yours**, and not a systemd service, Docker/Kubernetes container, or `tmux`/`screen`/`sshd`.

Children of a candidate are included. `sexton` never targets itself or its own ancestors.

Servers that are listening show their port in the `PORTS` column so you can sanity-check before
confirming. Anything you want left alone can be protected:

```toml
# ~/.config/sexton/config.toml
min_age = "2h"
protect = ["my-staging-app", "--port 8080"]   # regexes against the command line
```

## Safety and privacy

- **Dry run by default.** `scan` is read-only; `clean` asks for confirmation, and refuses to run
  without a terminal unless you pass `--yes`.
- **No PID-reuse accidents.** Before every signal it re-checks the process's start time, so a recycled
  PID is never hit.
- **Graceful first.** SIGTERM, a grace period, then SIGKILL only for what's left.
- **Never reads environment variables** (`/proc/<pid>/environ`), where secrets live. It reads only the
  command line, which is shown with obvious credentials (`--token ...`, `KEY=...`, `user:pass@`, `sk-...`)
  redacted.
- **No network access, no telemetry**, and it only ever acts on your own user's processes.

## Adding a rule

Rules live in `src/sexton/rules.py`. A rule is a regex over the program and its first few arguments.
Add a test case in `tests/test_rules.py` for both what it should match and a lookalike it must not.

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

## Status

Early (0.1). Linux only. Ideas: per-agent profiles, a memory-pressure
trigger, macOS support.

## License

MIT
