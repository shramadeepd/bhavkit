from typer.testing import CliRunner

from bhavkit import __version__
from bhavkit.cli import app

runner = CliRunner()


def test_version_long_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"bhavkit {__version__}" in result.stdout


def test_version_short_flag() -> None:
    result = runner.invoke(app, ["-V"])
    assert result.exit_code == 0
    assert f"bhavkit {__version__}" in result.stdout


def test_version_matches_package_metadata() -> None:
    import importlib.metadata

    assert __version__ == importlib.metadata.version("bhavkit")


def test_version_does_not_run_commands() -> None:
    result = runner.invoke(app, ["-V", "init"])
    assert result.exit_code == 0
    assert "bhavkit " in result.stdout