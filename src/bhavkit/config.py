from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, TypeAdapter, field_validator

DEFAULT_CONFIG_PATHS = (
    Path("bhavkit.toml"),
    Path.home() / ".config" / "bhavkit" / "config.toml",
)
ENV_PREFIX = "BHAV_"

DEFAULT_CONFIG_TOML = """\
# bhavkit default configuration (auto-created by `bhavkit init`).
# Every setting below already matches the built-in defaults, so the tool
# works with zero configuration. Edit this file to override.
# Precedence: CLI flags > BHAV_* env vars > this file > defaults.
# See bhavkit.toml.example for every option and what it does.

db_path = "bhavkit.duckdb"
data_dir = "data"
source = "nse"
nse_base_url = "https://nsearchives.nseindia.com"
concurrency = 4
retries = 5
backoff_base = 1.0
rate_limit_sleep = 0.35
timeout = 30.0
"""


class Config(BaseModel):
    """Resolved configuration. Precedence: CLI overrides > env > TOML > defaults."""

    db_path: Path = Field(default=Path("bhavkit.duckdb"))
    data_dir: Path = Field(default=Path("data"))
    concurrency: int = Field(default=4, ge=1, le=32)
    retries: int = Field(default=5, ge=0, le=20)
    backoff_base: float = Field(default=1.0, ge=0.1)
    rate_limit_sleep: float = Field(default=0.35, ge=0.0)
    timeout: float = Field(default=30.0, ge=1.0)
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 bhavkit/0.1"
    )
    source: str = Field(default="nse")
    nse_base_url: str = Field(default="https://nsearchives.nseindia.com")
    local_dir: Path | None = Field(default=None)
    verbose: bool = False

    @field_validator("source")
    @classmethod
    def _valid_source(cls, value: str) -> str:
        if value not in {"nse", "local"}:
            raise ValueError("source must be one of: nse, local")
        return value


def _load_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _flatten(data: dict, prefix: str = "") -> dict[str, object]:
    """Flatten a nested TOML dict into dotted key -> value pairs."""
    out: dict[str, object] = {}
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{dotted}."))
        else:
            out[dotted] = value
    return out


def load_config(
    config_file: Path | str | None = None,
    overrides: dict[str, object] | None = None,
) -> Config:
    """Merge defaults, TOML file(s), env vars (BHAV_*), and CLI overrides."""
    merged: dict[str, object] = {}
    paths = [Path(config_file)] if config_file else list(DEFAULT_CONFIG_PATHS)
    for path in paths:
        merged.update(_flatten(_load_toml(path)))

    for key, value in os.environ.items():
        if key.startswith(ENV_PREFIX):
            flat = key[len(ENV_PREFIX) :].lower()
            merged[flat] = value

    merged.update(overrides or {})
    return TypeAdapter(Config).validate_python(merged)


def default_config_path() -> Path:
    return DEFAULT_CONFIG_PATHS[0]


def effective_config_file() -> Path:
    """First existing config file, else the default project path."""
    for path in DEFAULT_CONFIG_PATHS:
        if path.is_file():
            return path
    return DEFAULT_CONFIG_PATHS[0]


def write_default_config(path: Path) -> bool:
    """Create a default config file at `path` if it does not exist.

    Returns True when the file was written, False if one was already present.
    """
    if path.is_file():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TOML)
    return True


def config_keys() -> list[str]:
    return sorted(Config.model_fields)


def _coerce_value(key: str, raw_value: str) -> object:
    """Validate a raw CLI value against the field and return the coerced value."""
    if key not in Config.model_fields:
        raise KeyError(f"unknown setting {key!r}; valid keys: {', '.join(config_keys())}")
    model = Config.model_validate({key: raw_value})
    return getattr(model, key)


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def set_config_option(path: Path, key: str, raw_value: str) -> bool:
    """Write `key = <value>` into the config file, preserving comments.

    Updates an existing `key` line in place, or appends a new one. Returns True
    if the file changed, False if the key already held the same value.
    """
    value = _coerce_value(key, raw_value)
    write_default_config(path)
    lines = path.read_text().splitlines(keepends=True)
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    literal = _toml_literal(value)
    for i, line in enumerate(lines):
        if pattern.match(line):
            indent = line[: len(line) - len(line.lstrip())]
            updated = f"{indent}{key} = {literal}\n"
            if line == updated:
                return False
            lines[i] = updated
            path.write_text("".join(lines))
            return True
    lines.append(f"{key} = {literal}\n")
    path.write_text("".join(lines))
    return True


def unset_config_option(path: Path, key: str) -> bool:
    """Remove a `key = ...` line from the config file. Returns True if removed."""
    if key not in Config.model_fields:
        raise KeyError(f"unknown setting {key!r}; valid keys: {', '.join(config_keys())}")
    if not path.is_file():
        return False
    lines = path.read_text().splitlines(keepends=True)
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    kept, removed = [], False
    for line in lines:
        if pattern.match(line) and not removed:
            removed = True
            continue
        kept.append(line)
    if removed:
        path.write_text("".join(kept))
    return removed