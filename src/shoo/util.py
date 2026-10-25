"""Formatting helpers, including redaction of anything that looks like a credential."""

from __future__ import annotations

import os
import re
from pathlib import Path

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


_XDG = {"config": ("XDG_CONFIG_HOME", ".config"), "state": ("XDG_STATE_HOME", ".local/state")}


def xdg_dir(kind: str) -> Path:
    """$XDG_CONFIG_HOME or $XDG_STATE_HOME, with the standard fallbacks under ~."""
    var, fallback = _XDG[kind]
    return Path(os.environ.get(var) or Path.home() / fallback)


_SECRET_WORDS = r"token|key|secret|passw(?:or)?d|passwd|auth|credential|bearer"
_REDACTIONS = (
    # Authorization: Bearer abc (curl -H ...), before the generic rules split it up. The scheme
    # word is only swallowed when there is one, so the next argument (often the URL) survives.
    (re.compile(r"(?i)\b((?:proxy-)?authorization)\s*:\s*(?:(?:bearer|basic|digest|token)\s+)?[^\s'\"]+"),
     r"\1: ***"),
    # Other credential-carrying headers: x-api-key:, Cookie:, X-Auth-Token:, ...
    (re.compile(r"(?i)\b([\w-]*(?:api[-_]?key|token|secret|cookie|session|auth)[\w-]*)\s*:\s*[^\s'\"]+"),
     r"\1: ***"),
    # A bare bearer token; long enough that it isn't an ordinary word
    (re.compile(r"(?i)\b(bearer)\s+[\w.~+/=-]{16,}"), r"\1 ***"),
    # JWTs, wherever they appear
    (re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]+"), "***"),
    # --api-key=abc, --password=abc
    (re.compile(rf"(?i)(--?[\w-]*(?:{_SECRET_WORDS})[\w-]*)=\S+"), r"\1=***"),
    # --token abc: only a value that isn't itself a flag, so a boolean like `--no-auth --port 80`
    # keeps its next argument. A multi-word value can't be told apart from arguments; best effort.
    (re.compile(rf"(?i)(--?[\w-]*(?:{_SECRET_WORDS})[\w-]*)\s+(?!-)\S+"), r"\1 ***"),
    # mysql -pSECRET, attached to the flag (-p8080 is a port, so not digits only)
    (re.compile(r"(?<=\s)(-p)(?!\d+(?:\s|$))\S+"), r"\1***"),
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
