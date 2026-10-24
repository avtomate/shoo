"""Optional config at $XDG_CONFIG_HOME/sexton/config.toml (default ~/.config/sexton/config.toml).

    min_age = "2h"                    # default: 1h
    protect = ["my-important-app", "port 8080"]   # regexes matched against the command line
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .util import parse_duration


@dataclass(frozen=True)
class Config:
    min_age_s: float | None = None
    protect: tuple[re.Pattern, ...] = ()


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "sexton" / "config.toml"


def load(path: Path | None = None) -> Config:
    path = path or default_path()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    min_age = data.get("min_age")
    return Config(
        min_age_s=parse_duration(str(min_age)) if min_age is not None else None,
        protect=tuple(re.compile(p) for p in data.get("protect", [])),
    )
