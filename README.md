# shoo

[![test](https://github.com/avtomate/shoo/actions/workflows/test.yml/badge.svg)](https://github.com/avtomate/shoo/actions/workflows/test.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Linux](https://img.shields.io/badge/platform-linux-lightgrey)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Clean up the processes your coding agents leave behind.**

Agents start MCP servers, headless browsers, dev servers and background tasks, then the session
ends and those processes keep running, holding hundreds of megabytes each. `shoo` finds the ones
that are orphaned and idle, shows you exactly what they are, and cleans them up when you say so,
or automatically on a timer.

![shoo finding leftovers, cleaning them, and showing the log](docs/demo.gif)

<sub>Recorded from real runs against simulated leftovers. They were started seconds earlier, hence
the `0m` ages; the demo's config sets `min_age` to 0.</sub>

## Quick start

Requires Linux and Python 3.11+. No dependencies, no root.

```bash
pipx install git+https://github.com/avtomate/shoo

shoo                 # see what's lying around (changes nothing)
shoo clean           # clean it up (asks first)
```

Happy with what it finds? Let it run on its own:

```bash
shoo schedule enable --dry-run   # watch first: record what it would clean, kill nothing
shoo log                         # a few days later, review
shoo schedule enable             # go live
```

## How it decides

A process is a **candidate** only if **all** of these are true:

1. **It's a known agent or dev tool:** MCP servers, headless browsers, Playwright drivers, JS and
   Python dev servers, language servers, agent CLIs, background tasks from finished Claude Code
   sessions, `tail -f`-style watchers (`shoo rules` lists them). Matching looks at the program and
   its first few arguments, never at directory names, so a project called `my-mcp` doesn't make
   everything inside it look like an MCP server.
2. **It's orphaned:** the session that started it is gone (re-parented to init or your
   `systemd --user`) and it isn't attached to a live terminal. Something launched through a shell
   wrapper (`bash -c "npm run dev"`) counts as orphaned if the wrapper is.
3. **It's old enough:** running longer than `--min-age` (1h by hand, 6h on the timer).
4. **It's yours,** and not a systemd service, a Docker or Kubernetes container, or
   `tmux`, `screen` or `sshd`.

Its children go with it. A candidate tree is then **held back** (listed, not cleaned) when:

- **someone is using it:** anything outside the tree has a live TCP connection to it (a browser
  tab, an SSH tunnel), or
- **it hasn't been idle long enough:** with `--require-idle` (2h on the timer), shoo must have
  watched the whole tree stay under 1% CPU for that long, across runs. Children that already
  exited are counted too, so a loop that keeps spawning short commands isn't mistaken for idle.

`shoo scan --why` lists your processes that were *not* picked, and why. It's the quickest way to
spot a leftover no rule catches yet.

## Reading the output

| Column | Meaning |
| --- | --- |
| `MEM` | Proportional memory (PSS): shared pages are split between the processes sharing them, so the total is what you'd actually get back. Plain RSS would count Chrome's shared memory a dozen times. |
| `CPU%` | CPU over a short sample (`--sample SECS`, default 2). |
| `IDLE` | How long shoo has watched the whole tree sit idle; `new` the first time it sees it. |
| `CONN` | Live TCP connections from *outside* the tree. |
| `PORTS` | Ports it's listening on. |

## Commands

| Command | What it does |
| --- | --- |
| `shoo` / `shoo scan` | List leftovers. Changes nothing. `--why` adds what was skipped; `--json` for scripts. |
| `shoo clean` | List, ask, then SIGTERM, wait `--grace` seconds (default 5), SIGKILL what's left. `-y` skips the prompt; `--dry-run` records instead of killing. |
| `shoo schedule enable` | Install an hourly systemd user timer. `--dry-run`, `--every`, `--min-age`, `--require-idle`. |
| `shoo schedule status` / `disable` | Show the mode and next run / remove the timer. |
| `shoo log` | What was cleaned, or would have been in dry-run. `-n` for more. |
| `shoo rules` | What it looks for. |

Options for `scan` and `clean`:

| Option | Default | |
| --- | --- | --- |
| `--min-age DURATION` | `1h` | Ignore anything younger (`30m`, `2h`, `1d`). |
| `--require-idle DURATION` | off | Only clean trees watched idle this long. |
| `--include-active` | off | Also clean trees with live outside connections. |
| `--protect REGEX` | | Never touch matching command lines. Repeatable. |
| `--sample SECS` | `2` | CPU measurement window; `0` to skip. |
| `--config PATH` | `~/.config/shoo/config.toml` | |

Exit codes: `0` success; `1` you declined at the prompt, or a process couldn't be signalled;
`2` bad arguments, or `clean` was run without a terminal and without `--yes`.

## Configuration

```toml
# ~/.config/shoo/config.toml
min_age = "2h"
protect = ["my-staging-app", "--port 8080"]   # regexes against the command line
```

## Safety and privacy

- **Read-only by default.** `scan` changes nothing. `clean` asks first and refuses to run without a
  terminal unless you pass `--yes`. `--dry-run` never signals anything.
- **No PID-reuse accidents.** It re-checks each process's start time right before signalling, so a
  recycled PID is never hit.
- **Graceful first:** SIGTERM, a grace period, then SIGKILL only for what's left.
- **Never reads environment variables** (`/proc/<pid>/environ`), where secrets live. It reads only
  command lines, and redacts obvious credentials (`--token ...`, `KEY=...`, `user:pass@`, `sk-...`)
  before showing or logging them.
- **Local only.** No network access, no telemetry. It only ever acts on your own user's processes,
  and keeps its state (idle history, log) in `~/.local/state/shoo`, readable only by you.

## FAQ

**I have "zombie" processes eating RAM. Will this fix that?**
Probably, but they're likely not zombies. A true zombie (`Z` in `ps`) has already exited and uses
no memory; it disappears when its parent does, and nothing can kill it. What uses memory is an
*orphaned live* process, which is what shoo cleans. If real zombies exist, shoo tells you and
explains why there's nothing to do.

**Will it kill my Docker containers, tmux sessions, or the agent I'm running right now?**
No. Containers and systemd services are excluded by cgroup; `tmux`, `screen` and `sshd` are never
touched. Anything in a live terminal, or whose parent is still running (like the tools your current
agent session is using), isn't orphaned and so isn't a candidate.

**Why not earlyoom or systemd-oomd?**
They solve a different problem. They step in when memory is nearly gone and kill whatever is
biggest, which might be the thing you care about. shoo is targeted and early: it removes known
leftovers before they add up. They work well together.

**It cleaned something I wanted.**
Add it to `protect` in the config. Please also open an issue with the command line (redact anything
private), so the rule can be tightened.

**Does it need root? Does it work on macOS?**
No root: it only acts on your own processes. Linux only for now; it reads `/proc`.

## Uninstall

```bash
shoo schedule disable          # remove the timer, if you enabled it
pipx uninstall shoo
rm -rf ~/.local/state/shoo ~/.config/shoo
```

## Contributing

Reports of what shoo gets wrong on real machines are the most useful contribution: something it
flagged that it shouldn't have, or a leftover it missed. There are issue templates for both. To
add a rule or send a fix, see [CONTRIBUTING.md](CONTRIBUTING.md); changes are tracked in
[CHANGELOG.md](CHANGELOG.md). Please report security problems privately, as described in
[SECURITY.md](SECURITY.md). This project follows a [code of conduct](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)
