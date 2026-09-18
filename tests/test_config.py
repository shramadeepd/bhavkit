from pathlib import Path

import pytest

from bhavkit.config import (
    DEFAULT_CONFIG_TOML,
    Config,
    config_keys,
    effective_config_file,
    load_config,
    set_config_option,
    unset_config_option,
    write_default_config,
)


def _tmp_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "bhavkit.toml"
    monkeypatch.setattr("bhavkit.config.DEFAULT_CONFIG_PATHS", (cfg,))
    return cfg


def test_write_default_config_creates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    assert write_default_config(cfg) is True
    assert cfg.is_file()
    assert "concurrency = 4" in cfg.read_text()


def test_write_default_config_does_not_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    cfg.write_text('source = "local"\n')
    assert write_default_config(cfg) is False
    assert cfg.read_text() == 'source = "local"\n'


def test_default_file_loads_into_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    write_default_config(cfg)
    loaded = load_config()
    assert loaded.db_path == Path("bhavkit.duckdb")
    assert loaded.source == "nse"
    assert loaded.concurrency == 4


def test_effective_config_file_prefers_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    assert effective_config_file() == cfg  # nothing exists -> default project path
    cfg2 = tmp_path / "user.toml"
    cfg2.write_text("")
    monkeypatch.setattr("bhavkit.config.DEFAULT_CONFIG_PATHS", (Path("nope.toml"), cfg2))
    assert effective_config_file() == cfg2  # first existing wins


def test_set_config_option_appends_and_roundtrips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    assert set_config_option(cfg, "concurrency", "8") is True
    assert set_config_option(cfg, "source", "local") is True
    loaded = load_config()
    assert loaded.concurrency == 8
    assert loaded.source == "local"
    assert isinstance(loaded.db_path, Path)  # untouched default

    text = cfg.read_text()
    assert 'concurrency = 8' in text
    assert 'source = "local"' in text


def test_set_config_option_updates_in_place_keeps_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    cfg.write_text("# my comment\nretries = 3\n")
    assert set_config_option(cfg, "retries", "5") is True
    text = cfg.read_text()
    assert text.startswith("# my comment\n")
    assert "retries = 5" in text
    assert "retries = 3" not in text

    assert set_config_option(cfg, "retries", "5") is False  # unchanged


def test_set_config_option_coerces_bool_float_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    set_config_option(cfg, "backoff_base", "0.5")
    set_config_option(cfg, "timeout", "45")
    loaded = load_config()
    assert loaded.backoff_base == 0.5
    assert loaded.timeout == 45


def test_set_config_option_unknown_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    with pytest.raises(KeyError, match="unknown setting"):
        set_config_option(cfg, "bogus", "1")


def test_set_config_option_invalid_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    with pytest.raises(ValueError):  # pydantic rejects source+"nse/foobar"
        set_config_option(cfg, "source", "nse2")
    with pytest.raises(ValueError):  # backoff_base < 0.1
        set_config_option(cfg, "backoff_base", "0.01")


def test_unset_config_option(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    set_config_option(cfg, "concurrency", "8")
    assert unset_config_option(cfg, "concurrency") is True
    assert "concurrency" not in cfg.read_text()
    assert load_config().concurrency == 4  # falls back to default
    assert unset_config_option(cfg, "concurrency") is False
    with pytest.raises(KeyError, match="unknown setting"):
        unset_config_option(cfg, "bogus")


def test_config_keys_are_config_fields() -> None:
    assert set(config_keys()) == set(Config.model_fields)
    assert "concurrency" in config_keys()


def test_toml_literal_is_idempotent_via_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _tmp_patch(tmp_path, monkeypatch)
    write_default_config(cfg)
    set_config_option(cfg, "db_path", "dir with space/db.duckdb")
    loaded = load_config()
    assert loaded.db_path == Path("dir with space/db.duckdb")
    assert "db_path = \"dir with space/db.duckdb\"" in cfg.read_text()


def test_toml_templates_parse() -> None:
    import tomllib

    tomllib.loads(DEFAULT_CONFIG_TOML)
    example = Path("bhavkit.toml.example")
    if example.is_file():
        tomllib.loads(example.read_text())