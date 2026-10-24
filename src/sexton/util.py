"""Formatting helpers, including redaction of anything that looks like a credential."""

from __future__ import annotations

import re

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd]?)$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """'90m' -> 5400.0. A bare number is seconds."""
    m = _DURATION.match(text.strip().lower())
    if not m:
        raise ValueError(f"bad duration {text!r} (try 30m, 2h, 1d)")
    return float(m.group(1)) * _UNITS[m.group(2)]


def fmt_age(seconds: float) -> str:
    seconds = int(seconds)
    if seconds >= 86400:
        return f"{seconds // 86400}d{seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60}m"
    return f"{seconds // 60}m"


def fmt_kb(kb: int) -> str:
    if kb >= 1024 * 1024:
        return f"{kb / 1024 / 1024:.1f}G"
    if kb >= 1024:
        return f"{kb / 1024:.0f}M"
    return f"{kb}K"


_SECRET_WORDS = r"token|key|secret|passw(?:or)?d|passwd|auth|credential|bearer"
_REDACTIONS = (
    # --api-key=abc, --token abc, -p=abc
    (re.compile(rf"(?i)(--?[\w-]*(?:{_SECRET_WORDS})[\w-]*)([=\s]+)\S+"), r"\1\2***"),
    # API_KEY=abc, GITHUB_TOKEN=abc
    (re.compile(rf"(?i)\b([\w]*(?:{_SECRET_WORDS})[\w]*)=\S+"), r"\1=***"),
    # https://user:pass@host
    (re.compile(r"(://)[^/\s:@]+:[^/\s@]+@"), r"\1***@"),
    # well-known token shapes
    (re.compile(r"\b(?:sk-[\w-]{8,}|gh[pousr]_\w{8,}|xox[abp]-[\w-]{8,}|AKIA[0-9A-Z]{12,})\b"), "***"),
)


def redact(cmdline: str) -> str:
    for pattern, repl in _REDACTIONS:
        cmdline = pattern.sub(repl, cmdline)
    return cmdline


def truncate(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"
