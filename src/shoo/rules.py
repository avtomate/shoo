"""What counts as a reclaimable process.

A process is only ever a candidate if ALL of these hold:
  1. it matches a known agent / dev-tool rule (RULES),
  2. it is orphaned: its parent is gone and it is not attached to a live terminal,
  3. it has been running at least `min_age_s`,
  4. it is yours, and not a managed service, container, or protected program.

Children of a candidate are swept up with it. Whether a candidate is actually *cleaned* also
depends on activity (CPU between runs, live connections); see scan.py.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .procs import Proc, tty_state
from .util import fmt_age


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern
    description: str
    head_tokens: int = 6  # match only the program and its first N arguments...
    full: bool = False  # ...unless the signature can sit anywhere in the command line
    skip_flags: bool = False  # ignore -x/--flag tokens when picking the head
    also: re.Pattern | None = None  # extra pattern that must match somewhere in the full command
    shells: bool = False  # the only kind of rule allowed to match a shell


def _rule(name: str, regex: str, description: str, *, also: str | None = None, **kw) -> Rule:
    return Rule(
        name,
        re.compile(regex, re.IGNORECASE),
        description,
        also=re.compile(also, re.IGNORECASE) if also else None,
        **kw,
    )


RULES: tuple[Rule, ...] = (
    _rule(
        "mcp-server",
        r"(?:^|[\s/@_-])mcp(?:[\s/_-]|$)|modelcontextprotocol",
        "MCP servers spawned by an agent session",
        head_tokens=3,
        skip_flags=True,
    ),
    _rule(
        "headless-browser",
        r"^(?:chrom(?:e|ium)\S*|headless_shell|firefox)(?:\s|$)",
        "Headless Chrome / Firefox left running",
        head_tokens=2,
        also=r"--(?:headless|remote-debugging-(?:port|pipe))",
    ),
    _rule(
        "browser-automation",
        r"\brun-driver\b",
        "Playwright drivers left running",
        full=True,
    ),
    _rule(
        "node-dev-server",
        r"(?:^|\s)(?:vite|webpack-dev-server|nodemon|ts-node-dev|storybook|vitest|parcel)(?:\s|$)"
        r"|(?:^|\s)next(?:-server|\s+dev)(?:\s|$)|(?:^|\s)(?:astro|nuxt|remix)\s+dev\b"
        r"|(?:^|\s)tsx\s+watch\b|(?:^|\s)jest\s+--watch",
        "JavaScript dev servers and watchers",
    ),
    _rule(
        "node-launcher",
        r"^(?:npm|npx|yarn|pnpm)\s+(?:run|exec|dev|start|watch|dlx)\b",
        "npm / npx / yarn / pnpm wrappers that outlived their job",
    ),
    _rule(
        "python-dev-server",
        r"(?:^|\s)(?:uvicorn|gunicorn)\s.*--reload|(?:^|\s)flask\s+run\b|-m\s+http\.server"
        r"|(?:^|\s)streamlit\s+run\b|manage\.py\s+runserver|(?:^|\s)jupyter[- ](?:lab|notebook)"
        r"|ipykernel_launcher",
        "Python dev servers, notebooks and kernels",
    ),
    _rule(
        "language-server",
        r"tsserver|typescript-language-server|pyright-langserver|(?:^|\s)gopls(?:\s|$)"
        r"|rust-analyzer|eslint_d",
        "Editor language servers whose editor is gone",
    ),
    _rule(
        "agent-cli",
        r"^(?:claude|codex|gemini|aider|opencode)(?:\s|$)",
        "Coding-agent CLIs whose terminal is gone",
        head_tokens=1,
    ),
    _rule(
        "agent-task",
        r"/shell-snapshots/snapshot-[\w.-]+\.sh\b",
        "Background shell tasks from a finished Claude Code session",
        full=True,
        shells=True,
    ),
    _rule(
        "watcher",
        r"^(?:tail\s+-[fF]|inotifywait|fswatch)\b",
        "Log tails and file watchers",
        head_tokens=2,
    ),
)

# Shells are only matched by `shells=True` rules: a wrapper's command line mentions whatever it
# runs, so ordinary rules would misfire on it.
SHELLS = frozenset({"bash", "sh", "dash", "zsh", "fish"})

# Programs we refuse to touch even if a rule somehow matches them or their parent.
PROTECTED_COMMS = frozenset(
    {"systemd", "sshd", "sshd-session", "tmux: server", "tmux", "screen", "dockerd", "containerd"}
)
PROTECTED_CGROUP_MARKERS = ("docker", "containerd", "libpod", "kubepods", "lxc", "/system.slice/")


@dataclass(frozen=True)
class Policy:
    min_age_s: float = 3600.0
    uid: int = field(default_factory=os.getuid)
    protect: tuple[re.Pattern, ...] = ()


@dataclass(frozen=True)
class Finding:
    proc: Proc
    rule: str  # rule name, or "child"
    reasons: tuple[str, ...]
    root_pid: int | None = None  # for children: the candidate they were swept up with
    cpu_pct: float | None = None  # over the --sample window
    ports: tuple[int, ...] = ()
    pss_kb: int | None = None
    idle_s: float | None = None  # roots only: how long the whole tree has been idle (None = unknown)
    connections: int = 0  # roots only: live connections from outside the tree

    @property
    def root(self) -> int:
        return self.root_pid if self.root_pid is not None else self.proc.pid

    @property
    def mem_kb(self) -> int:
        return self.pss_kb if self.pss_kb is not None else self.proc.rss_kb


def _head(cmdline: str, n: int, skip_flags: bool = False) -> str:
    """The program and its first n-1 arguments, with directories stripped.

    Directory names (a project called `my-mcp`, a cwd under `.claude/`) say nothing about what a
    process is. Two things that look like paths are not: npm scopes (`@org/pkg`) and packages
    inside node_modules, where the package directory *is* the program.
    """
    out = []
    for token in cmdline.split():
        if skip_flags and token.startswith("-"):
            continue
        if token.startswith("@"):
            pass
        elif "node_modules/" in token:
            token = token.rsplit("node_modules/", 1)[1]
            if token.startswith(".bin/"):
                token = token.rsplit("/", 1)[-1]
        else:
            token = token.rsplit("/", 1)[-1]
        out.append(token)
        if len(out) == n:
            break
    return " ".join(out)


def is_shell(proc: Proc) -> bool:
    return proc.comm in SHELLS


def match_rule(proc: Proc) -> Rule | None:
    shell = is_shell(proc)
    for rule in RULES:
        if shell and not rule.shells:
            continue
        text = proc.cmdline if rule.full else _head(proc.cmdline, rule.head_tokens, rule.skip_flags)
        if rule.pattern.search(text) and (rule.also is None or rule.also.search(proc.cmdline)):
            return rule
    return None


def protected_reason(proc: Proc, policy: Policy) -> str | None:
    if proc.pid <= 1:
        return "init"
    if proc.uid != policy.uid:
        return "owned by another user"
    if proc.comm in PROTECTED_COMMS:
        return f"protected program ({proc.comm})"
    if proc.cgroup.rstrip("/").endswith(".service") or any(
        m in proc.cgroup for m in PROTECTED_CGROUP_MARKERS
    ):
        return "managed service or container"
    for pat in policy.protect:
        if pat.search(proc.cmdline):
            return f"matches protect rule {pat.pattern!r}"
    return None


def launched_by_desktop(proc: Proc) -> bool:
    """Started on purpose from a desktop launcher (GNOME and others put these in app-*.scope).

    Such apps can have the systemd user manager as their parent from the start, which would
    otherwise look exactly like an orphan. Terminals use their own scopes (vte-spawn-*, tmux-spawn-*),
    so leftovers from a closed terminal are still caught.
    """
    leaf = proc.cgroup.rstrip("/").rsplit("/", 1)[-1]
    return leaf.startswith("app-") and leaf.endswith(".scope")


def _top(proc: Proc, procs: dict[int, Proc]) -> Proc:
    """Walk up through shell wrappers (`bash -c "npm run dev"`) to what actually launched it."""
    top = proc
    while True:
        parent = procs.get(top.ppid)
        if parent is None or parent.uid != top.uid or not is_shell(parent) or parent is top:
            return top
        top = parent


def orphan_reason(proc: Proc, procs: dict[int, Proc]) -> str | None:
    """Why this process counts as orphaned, or None if it still has an owner.

    Shell wrappers (`bash -c "npm run dev"`) are looked through: a dev server is orphaned if the
    shell that launched it is.
    """
    top = _top(proc, procs)
    tty = tty_state(top.tty_nr)
    if tty == "alive" or launched_by_desktop(top):
        return None
    parent = procs.get(top.ppid)
    reparented = top.ppid == 1 or (
        parent is not None and parent.comm == "systemd" and parent.uid == top.uid
    )
    if not reparented:
        return None
    return "terminal closed, parent gone" if tty == "gone" else "parent gone, no terminal"


def _ancestors(pid: int, procs: dict[int, Proc]) -> set[int]:
    seen = set()
    while pid in procs and pid not in seen:
        seen.add(pid)
        pid = procs[pid].ppid
    return seen


def classify(procs: dict[int, Proc], policy: Policy, own_pid: int | None = None) -> list[Finding]:
    """Candidates first (largest memory first), each followed by the children swept up with it."""
    skip = _ancestors(own_pid if own_pid is not None else os.getpid(), procs)

    roots: list[Finding] = []
    for p in procs.values():
        if p.pid in skip or p.state == "Z" or p.age_s < policy.min_age_s:
            continue
        if protected_reason(p, policy):
            continue
        rule = match_rule(p)
        if rule is None:
            continue
        orphan = orphan_reason(p, procs)
        if orphan is None:
            continue
        roots.append(Finding(p, rule.name, (orphan, f"matches {rule.name}")))

    children_of: dict[int, list[Proc]] = {}
    for p in procs.values():
        children_of.setdefault(p.ppid, []).append(p)

    out: list[Finding] = []
    claimed = {f.proc.pid for f in roots}
    for root in sorted(roots, key=lambda f: f.proc.rss_kb, reverse=True):
        out.append(root)
        stack = [root.proc.pid]
        while stack:
            for child in children_of.get(stack.pop(), []):
                if child.pid in claimed or child.pid in skip or child.state == "Z":
                    continue
                if protected_reason(child, policy):
                    continue
                claimed.add(child.pid)
                stack.append(child.pid)
                out.append(
                    Finding(child, "child", (f"child of {root.proc.pid}",), root_pid=root.proc.pid)
                )
    return out


def explain(
    procs: dict[int, Proc], policy: Policy, candidates: set[int], own_pid: int | None = None
) -> list[tuple[Proc, str]]:
    """For `scan --why`: your processes that are orphaned or match a rule, but weren't picked."""
    skip = _ancestors(own_pid if own_pid is not None else os.getpid(), procs)
    out = []
    for p in sorted(procs.values(), key=lambda p: p.pid):
        if p.pid in candidates or p.pid in skip or p.uid != policy.uid or p.state == "Z":
            continue
        rule, orphan = match_rule(p), orphan_reason(p, procs)
        if rule is None and orphan is None:
            continue
        if reason := protected_reason(p, policy):
            why = f"protected: {reason}"
        elif rule is None:
            why = "orphaned, but no rule matches"
        elif orphan is None:
            parent = procs.get(p.ppid)
            if tty_state(p.tty_nr) == "alive":
                why = f"matches {rule.name}, but attached to a live terminal"
            elif launched_by_desktop(_top(p, procs)):
                why = f"matches {rule.name}, but it was launched from the desktop"
            else:
                owner = f"{parent.comm} {parent.pid}" if parent else str(p.ppid)
                why = f"matches {rule.name}, but its parent ({owner}) is alive"
        else:
            why = f"matches {rule.name}, but too young ({fmt_age(p.age_s)} < {fmt_age(policy.min_age_s)})"
        out.append((p, why))
    return out
