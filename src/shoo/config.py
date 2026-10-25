"""Optional config at $XDG_CONFIG_HOME/shoo/config.toml (default ~/.config/shoo/config.toml).

    min_age = "2h"                    # default: 1h
    protect = ["my-important-app", "port 8080"]   # regexes matched against the command line
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .util import parse_duration, xdg_dir


@dataclass(frozen=True)
class Config:
    min_age_s: float | None = None
    protect: tuple[re.Pattern, ...] = ()


def default_path() -> Path:
    return xdg_dir("config") / "shoo" / "config.toml"


def load(path: Path | None = None) -> Config:
    """Load the config. A missing default file is fine; a missing file you named is an error,
    since silently running without your protect rules could kill what you meant to keep."""
    explicit = path is not None
    path = path or default_path()
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        if explicit:
            raise ValueError(f"config file not found: {path}") from None
        return Config()
    protect = data.get("protect", [])
    if not isinstance(protect, list) or not all(isinstance(p, str) for p in protect):
        raise ValueError(f'{path}: protect must be a list of strings, e.g. protect = ["my-app"]')
    min_age = data.get("min_age")
    return Config(
        min_age_s=parse_duration(str(min_age)) if min_age is not None else None,
        protect=tuple(re.compile(p) for p in protect),
    )
