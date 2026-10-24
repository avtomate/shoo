"""Command line interface: `sexton scan` (default, read-only), `clean`, and `schedule`."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

from . import __version__, config, schedule
from .cleaner import clean
from .procs import CLK_TCK, listening_ports, read_proc, snapshot
from .rules import RULES, Finding, Policy, classify, with_metrics
from .util import fmt_age, fmt_kb, parse_duration, redact, truncate

DEFAULT_MIN_AGE = 3600.0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--min-age", help="ignore processes younger than this (e.g. 30m, 2h, 1d); default 1h")
    common.add_argument("--protect", action="append", default=[], metavar="REGEX",
                        help="never touch processes whose command line matches (repeatable)")
    common.add_argument("--sample", type=float, default=2.0, metavar="SECS",
                        help="seconds to measure CPU use over (0 to skip); default 2")
    common.add_argument("--config", type=Path, help="path to a config.toml")

    p = argparse.ArgumentParser(prog="sexton", description=__doc__)
    p.add_argument("--version", action="version", version=f"sexton {__version__}")
    sub = p.add_subparsers(dest="command")

    scan = sub.add_parser("scan", parents=[common], help="list reclaimable processes (changes nothing)")
    scan.add_argument("--json", action="store_true", help="machine-readable output")

    cp = sub.add_parser("clean", parents=[common], help="terminate reclaimable processes")
    cp.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    cp.add_argument("--grace", type=float, default=5.0, metavar="SECS",
                    help="seconds between SIGTERM and SIGKILL; default 5")

    sp = sub.add_parser("schedule", help="run `clean` automatically (systemd user timer)")
    actions = sp.add_subparsers(dest="action", required=True)
    en = actions.add_parser("enable", help="turn on automatic cleaning")
    en.add_argument("--every", default=schedule.DEFAULT_EVERY, help="how often to run; default 1h")
    en.add_argument("--min-age", default=schedule.DEFAULT_MIN_AGE,
                    help="only clean processes older than this; default 6h")
    actions.add_parser("disable", help="turn off automatic cleaning")
    actions.add_parser("status", help="show the next run and recent activity")

    sub.add_parser("rules", help="show what sexton looks for")
    return p


def _policy(args: argparse.Namespace) -> Policy:
    cfg = config.load(args.config)
    if args.min_age is not None:
        min_age = parse_duration(args.min_age)
    else:
        min_age = cfg.min_age_s if cfg.min_age_s is not None else DEFAULT_MIN_AGE
    protect = cfg.protect + tuple(re.compile(r) for r in args.protect)
    return Policy(min_age_s=min_age, protect=protect)


def _measure(findings: list[Finding], sample: float) -> list[Finding]:
    """Attach CPU% (over a short sample window) and listening ports to each finding."""
    before = {f.proc.pid: f.proc.cpu_ticks for f in findings}
    if sample > 0 and findings:
        time.sleep(sample)
    out = []
    for f in findings:
        cpu = None
        if sample > 0:
            now = read_proc(f.proc.pid)
            if now is not None and now.starttime == f.proc.starttime:
                cpu = (now.cpu_ticks - before[f.proc.pid]) / CLK_TCK / sample * 100
        out.append(with_metrics(f, cpu, listening_ports(f.proc.pid)))
    return out


def _find(args: argparse.Namespace) -> tuple[list[Finding], list]:
    procs = snapshot()
    findings = _measure(classify(procs, _policy(args)), args.sample)
    zombies = [p for p in procs.values() if p.state == "Z"]
    return findings, zombies


def _print_table(findings: list[Finding], zombies: list, hint: bool = True) -> None:
    if not findings:
        print("Nothing to clean up.")
    else:
        width = shutil.get_terminal_size((100, 20)).columns
        print(f"{'PID':>7} {'AGE':>6} {'RSS':>6} {'CPU%':>5}  {'KIND':<16} {'PORTS':<10} COMMAND")
        for f in findings:
            p = f.proc
            cpu = "-" if f.cpu_pct is None else f"{f.cpu_pct:.0f}"
            ports = ",".join(map(str, f.ports)) or "-"
            prefix = "  └ " if f.rule == "child" else ""
            cmd = truncate(prefix + redact(p.cmdline), max(20, width - 58))
            print(f"{p.pid:>7} {fmt_age(p.age_s):>6} {fmt_kb(p.rss_kb):>6} {cpu:>5}  {f.rule:<16} {ports:<10} {cmd}")
        total = sum(f.proc.rss_kb for f in findings)
        print(f"\n{len(findings)} processes, about {fmt_kb(total)} reclaimable."
              + (" Run `sexton clean` to clean them up." if hint else ""))
    if zombies:
        print(f"\nNote: {len(zombies)} zombie process(es) exist. Zombies are already dead and use no "
              "memory; they vanish when their parent exits or collects them. Nothing to kill.")


def _to_json(f: Finding) -> dict:
    p = f.proc
    return {
        "pid": p.pid, "ppid": p.ppid, "kind": f.rule, "reasons": list(f.reasons),
        "age_s": round(p.age_s), "rss_kb": p.rss_kb, "cpu_pct": f.cpu_pct,
        "ports": list(f.ports), "command": redact(p.cmdline),
    }


def cmd_scan(args: argparse.Namespace) -> int:
    findings, zombies = _find(args)
    if args.json:
        print(json.dumps([_to_json(f) for f in findings], indent=2))
    else:
        _print_table(findings, zombies)
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    findings, zombies = _find(args)
    _print_table(findings, zombies, hint=False)
    if not findings:
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to kill without a terminal to confirm. Pass --yes to override.", file=sys.stderr)
            return 2
        if input(f"\nTerminate these {len(findings)} processes? [y/N] ").strip().lower() != "y":
            print("Aborted.")
            return 1
    results = clean(findings, grace=args.grace)
    for pid, outcome in results.items():
        print(f"{pid:>7}  {outcome}")
    return 0 if "denied" not in results.values() else 1


def cmd_schedule(args: argparse.Namespace) -> int:
    if args.action == "enable":
        return schedule.enable(args.every, args.min_age)
    return schedule.disable() if args.action == "disable" else schedule.status()


def cmd_rules(_: argparse.Namespace) -> int:
    for r in RULES:
        print(f"{r.name:<18} {r.description}")
    print("\nA process is only touched if it matches a rule AND is orphaned AND is older than "
          "--min-age AND is yours AND is not a managed service or container.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    args = build_parser().parse_args(argv or ["scan"])
    handlers = {"scan": cmd_scan, "clean": cmd_clean, "schedule": cmd_schedule, "rules": cmd_rules}
    try:
        return handlers[args.command](args)
    except (ValueError, re.error) as e:
        print(f"sexton: {e}", file=sys.stderr)
        return 2
