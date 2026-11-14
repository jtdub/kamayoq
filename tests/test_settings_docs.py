"""Unit tests that prove the documents list each setting."""

from pathlib import Path

from kamayoq.settings import CONFIG_FILE_ENV, ENV_PREFIX, Settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"
README = PROJECT_ROOT / "README.md"


def setting_env_names() -> list[str]:
    """Return the environment variable of each setting and of the config file."""
    return [ENV_PREFIX + name.upper() for name in Settings.model_fields] + [
        CONFIG_FILE_ENV
    ]


def test_env_example_lists_every_setting() -> None:
    """List each KAMAYOQ_ variable in .env.example."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [name for name in setting_env_names() if name not in text]
    assert missing == []


def test_readme_lists_every_setting_and_the_run_command() -> None:
    """List each KAMAYOQ_ variable and the run command in README.md."""
    text = README.read_text(encoding="utf-8")
    missing = [name for name in setting_env_names() if name not in text]
    assert missing == []
    assert "uv run kamayoq serve" in text
