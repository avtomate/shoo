"""shoo: find and clean up orphaned agent and dev-tool processes.

`shoo` (same as `shoo scan`) only looks. `shoo clean` asks before it kills anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import __version__, config, schedule, state
from .cleaner import clean
from .rules import DEFAULT_MIN_AGE_S, RULES, Finding, Policy
from .scan import Report, run
from .util import fmt_age, fmt_kb, parse_duration, redact, truncate


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--min-age", help="ignore processes younger than this (e.g. 30m, 2h, 1d); default 1h")
    common.add_argument("--require-idle", metavar="DURATION",
                        help="only clean trees shoo has watched sit idle this long (across runs)")
    common.add_argument("--include-active", action="store_true",
                        help="also clean trees that have live connections")
    common.add_argument("--protect", action="append", default=[], metavar="REGEX",
                        help="never touch processes whose command line matches (repeatable)")
    common.add_argument("--sample", type=float, default=2.0, metavar="SECS",
                        help="seconds to measure CPU use over (0 to skip); default 2")
    common.add_argument("--config", type=Path, help="path to a config.toml")

    p = argparse.ArgumentParser(prog="shoo", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"shoo {__version__}")
    sub = p.add_subparsers(dest="command")

    sc = sub.add_parser("scan", parents=[common], help="list leftover processes (changes nothing)")
    sc.add_argument("--json", action="store_true", help="machine-readable output")
    sc.add_argument("--why", action="store_true",
                    help="also list your orphaned or rule-matching processes that were skipped, and why")

    cp = sub.add_parser("clean", parents=[common], help="terminate leftover processes")
    cp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    cp.add_argument("--dry-run", action="store_true", help="record what would be cleaned; kill nothing")
    cp.add_argument("--grace", type=float, default=5.0, metavar="SECS",
                    help="seconds between SIGTERM and SIGKILL; default 5")
    cp.add_argument("--allow-root", action="store_true", help=argparse.SUPPRESS)

    sp = sub.add_parser("schedule", help="clean automatically in the background (systemd user timer)")
    actions = sp.add_subparsers(dest="action", required=True)
    en = actions.add_parser("enable", help="turn on automatic cleaning")
    en.add_argument("--every", default=schedule.DEFAULT_EVERY, help="how often to run; default 1h")
    en.add_argument("--min-age", default=schedule.DEFAULT_MIN_AGE,
                    help="only clean processes older than this; default 6h")
    en.add_argument("--require-idle", default=schedule.DEFAULT_REQUIRE_IDLE,
                    help="only clean trees idle across runs this long; default 2h")
    en.add_argument("--dry-run", action="store_true",
                    help="watch-only: record what would be cleaned, kill nothing")
    en.add_argument("--allow-root", action="store_true", help=argparse.SUPPRESS)
    actions.add_parser("disable", help="turn off automatic cleaning")
    actions.add_parser("status", help="show mode and next run")

    lg = sub.add_parser("log", help="show what shoo cleaned (or would have, in dry-run)")
    lg.add_argument("-n", type=int, default=30, help="how many entries; default 30")

    sub.add_parser("rules", help="show what shoo looks for")
    return p


def _policy(args: argparse.Namespace) -> Policy:
    cfg = config.load(args.config)
    if args.min_age is not None:
        min_age = parse_duration(args.min_age)
    else:
        min_age = cfg.min_age_s if cfg.min_age_s is not None else DEFAULT_MIN_AGE_S
    protect = cfg.protect + tuple(re.compile(r) for r in args.protect)
    return Policy(min_age_s=min_age, protect=protect)


def _report(args: argparse.Namespace, explain: bool = False) -> Report:
    tracker = state.IdleTracker()
    report = run(
        _policy(args),
        sample=args.sample,
        require_idle_s=parse_duration(args.require_idle) if args.require_idle else None,
        include_active=args.include_active,
        tracker=tracker,
        explain_skipped=explain,
    )
    try:
        tracker.save()
    except OSError as e:
        print(f"shoo: couldn't save idle history ({e}); idle times won't accumulate", file=sys.stderr)
    return report


def _width(used: int) -> int:
    return max(20, shutil.get_terminal_size((120, 20)).columns - used)


def _rows(findings: list[Finding]) -> None:
    print(f"{'PID':>7} {'AGE':>6} {'MEM':>6} {'CPU%':>4} {'IDLE':>6} {'CONN':>4}  "
          f"{'KIND':<17} {'PORTS':<9} COMMAND")
    for f in findings:
        p, is_root = f.proc, f.root_pid is None
        cpu = "-" if f.cpu_pct is None else f"{f.cpu_pct:.0f}"
        idle = ("new" if f.idle_s is None else fmt_age(f.idle_s)) if is_root else ""
        conns = (str(f.connections) if f.connections else "-") if is_root else ""
        ports = ",".join(map(str, f.ports)) or "-"
        cmd = truncate(("" if is_root else "  └ ") + redact(p.cmdline), _width(69))
        print(f"{p.pid:>7} {fmt_age(p.age_s):>6} {fmt_kb(f.mem_kb):>6} {cpu:>4} {idle:>6} {conns:>4}  "
              f"{f.rule:<17} {ports:<9} {cmd}")


def _print_report(report: Report, hint: str | None = "Run `shoo clean` to clean them up.") -> None:
    ready = report.actionable
    if ready:
        _rows(ready)
        total = sum(f.mem_kb for f in ready)
        print(f"\n{len(ready)} processes, about {fmt_kb(total)} reclaimable." + (f" {hint}" if hint else ""))
    else:
        print("Nothing to clean up.")

    if report.held:
        print("\nHeld back (won't be cleaned):")
        for f in report.held_roots:
            tree = [x for x in report.findings if x.root == f.proc.pid]
            mem = fmt_kb(sum(x.mem_kb for x in tree))
            cmd = truncate(redact(f.proc.cmdline), _width(56))
            print(f"{f.proc.pid:>7} {mem:>6}  {report.held[f.proc.pid]:<40} {cmd}")

    if report.skipped:
        print("\nNot candidates (--why):")
        for p, why in report.skipped:
            print(f"{p.pid:>7}  {why:<58} {truncate(redact(p.cmdline), _width(68))}")

    if report.zombies:
        print(f"\nNote: {len(report.zombies)} zombie process(es) exist. Zombies are already dead and "
              "use no memory; they vanish when their parent exits or collects them. Nothing to kill.")


def _to_json(f: Finding, held: dict[int, str]) -> dict:
    p = f.proc
    return {
        "pid": p.pid, "ppid": p.ppid, "root": f.root, "kind": f.rule, "reasons": list(f.reasons),
        "age_s": round(p.age_s), "mem_kb": f.mem_kb, "rss_kb": p.rss_kb, "cpu_pct": f.cpu_pct,
        "idle_s": None if f.idle_s is None else round(f.idle_s), "connections": f.connections,
        "ports": list(f.ports), "held": held.get(f.root), "command": redact(p.cmdline),
    }


def cmd_scan(args: argparse.Namespace) -> int:
    report = _report(args, explain=args.why)
    if args.json:
        print(json.dumps([_to_json(f, report.held) for f in report.findings], indent=2))
    else:
        _print_report(report)
    return 0


def _log_record(f: Finding, action: str) -> dict:
    return {
        "ts": round(time.time()), "action": action, "pid": f.proc.pid, "kind": f.rule,
        "mem_kb": f.mem_kb, "age_s": round(f.proc.age_s), "command": redact(f.proc.cmdline),
    }


ROOT_REFUSAL = (
    "shoo: refusing to run as root. shoo acts on the current user's processes, and for root those "
    "are system daemons; only the systemd service check would protect them, and without systemd "
    "nothing would. Run it as the user whose agents leave processes behind. If you really mean "
    "it, pass --allow-root."
)


def _refuse_root(args: argparse.Namespace) -> bool:
    if os.geteuid() == 0 and not args.allow_root:
        print(ROOT_REFUSAL, file=sys.stderr)
        return True
    return False


def cmd_clean(args: argparse.Namespace) -> int:
    if _refuse_root(args):
        return 2
    report = _report(args)
    _print_report(report, hint=None)
    targets = report.actionable
    if not targets:
        return 0
    if args.dry_run:
        state.append_log([_log_record(f, "would-clean") for f in targets])
        print(f"\nDry run: would have terminated {len(targets)} processes. Nothing was killed.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to kill without a terminal to confirm. Pass --yes to override.", file=sys.stderr)
            return 2
        try:
            answer = input(f"\nTerminate these {len(targets)} processes? [y/N] ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
            print()
        if answer.strip().lower() != "y":
            print("Aborted.")
            return 1
    results = clean(targets, grace=args.grace)
    state.append_log([_log_record(f, results[f.proc.pid]) for f in targets])
    for pid, outcome in results.items():
        print(f"{pid:>7}  {outcome}")
    return 0 if "denied" not in results.values() else 1


def cmd_schedule(args: argparse.Namespace) -> int:
    if args.action == "enable":
        if _refuse_root(args):
            return 2
        return schedule.enable(args.every, args.min_age, args.require_idle, args.dry_run)
    return schedule.disable() if args.action == "disable" else schedule.status()


def cmd_log(args: argparse.Namespace) -> int:
    entries = state.read_log(args.n)
    if not entries:
        print("Nothing logged yet.")
        return 0
    for e in entries:
        when = datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d %H:%M")
        print(f"{when}  {e['action']:<11} {e['pid']:>7}  {e['kind']:<17} {fmt_kb(e['mem_kb']):>6}  "
              f"{truncate(e['command'], _width(64))}")
    return 0


def cmd_rules(_: argparse.Namespace) -> int:
    for r in RULES:
        print(f"{r.name:<18} {r.description}")
    print("\nA process is a candidate only if it matches a rule AND is orphaned AND is older than "
          "--min-age AND is yours AND is not a managed service or container. Trees with live "
          "connections are held back.")
    return 0


HANDLERS = {"scan": cmd_scan, "clean": cmd_clean, "schedule": cmd_schedule, "log": cmd_log,
            "rules": cmd_rules}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # No command means scan, including `shoo --min-age 2h`.
    if not argv or (argv[0] not in HANDLERS and argv[0] not in ("-h", "--help", "--version")):
        argv = ["scan", *argv]
    args = build_parser().parse_args(argv)
    try:
        return HANDLERS[args.command](args)
    except (ValueError, re.error) as e:
        print(f"shoo: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
