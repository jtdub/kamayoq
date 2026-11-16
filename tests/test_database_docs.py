"""Unit tests that prove the README tells how to migrate and how to add a table."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = PROJECT_ROOT / "README.md"
DOWNGRADE_WARNING = (
    "WARNING: `alembic downgrade base` deletes all kamayoq data. "
    "Make a backup before you run it."
)


def database_section() -> str:
    """Return the text of the Database section of the README."""
    text = README.read_text(encoding="utf-8")
    return text.split("\n## Database\n", 1)[1].split("\n## ", 1)[0]


def test_readme_database_section_names_command_and_rules() -> None:
    """Name the command, Postgres 18, the model rules, and the WARNING."""
    section = database_section()
    required = [
        "alembic upgrade head",
        "Postgres 18",
        "OrgScoped",
        "Classified",
        "UNCLASSIFIED_TABLES",
        DOWNGRADE_WARNING,
    ]
    assert [item for item in required if item not in section] == []
    assert section.index(DOWNGRADE_WARNING) < section.index("alembic downgrade base\n")
