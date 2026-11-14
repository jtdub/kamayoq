"""Unit tests that prove the community files of the project."""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ISSUE_TEMPLATE_DIR = PROJECT_ROOT / ".github" / "ISSUE_TEMPLATE"
SECURITY_POLICY = PROJECT_ROOT / "SECURITY.md"
CODE_OF_CONDUCT = PROJECT_ROOT / "CODE_OF_CONDUCT.md"
CONTRIBUTING = PROJECT_ROOT / "CONTRIBUTING.md"
README = PROJECT_ROOT / "README.md"
PULL_REQUEST_TEMPLATE = PROJECT_ROOT / ".github" / "pull_request_template.md"
ADVISORIES_URL = "https://github.com/jtdub/kamayoq/security/advisories/new"
SECURITY_POLICY_URL = "https://github.com/jtdub/kamayoq/blob/develop/SECURITY.md"
REPORT_ABUSE_URL = "https://github.com/contact/report-abuse"
MARKDOWN_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    ".github/pull_request_template.md",
)
ISSUE_FORMS = ("bug.yml", "feature.yml")
FORM_ELEMENT_TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
FRAGMENT_TYPES = ("added", "changed", "fixed", "removed", "security")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
RESPONSE_TIME = re.compile(r"\b\d+\s*(business\s+)?(day|hour|week)s?\b", re.IGNORECASE)
FENCED_CODE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`\n]*`")
INLINE_LINK_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REFERENCE_LINK_TARGET = re.compile(
    r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE
)
URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def load_yaml(path: Path) -> dict[str, Any]:
    """Return the YAML file, with each key and each scalar as a string."""
    document: dict[str, Any] = yaml.load(
        path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    return document


def markdown_without_code(text: str) -> str:
    """Return the Markdown text without its fenced code blocks and code spans."""
    return INLINE_CODE.sub("", FENCED_CODE.sub("", text))


def relative_links(path: Path) -> list[Path]:
    """Return the resolved file path of each relative link in a Markdown file."""
    text = markdown_without_code(path.read_text(encoding="utf-8"))
    targets = INLINE_LINK_TARGET.findall(text) + REFERENCE_LINK_TARGET.findall(text)
    return [
        (path.parent / target.split("#", 1)[0]).resolve()
        for target in targets
        if not URL_SCHEME.match(target) and not target.startswith("#")
    ]


def test_security_policy_sends_reports_to_private_advisories() -> None:
    """Send vulnerability reports to private advisories, not to an issue."""
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    assert ADVISORIES_URL in text
    assert "Report a vulnerability" in text
    assert "public issue" in text


def test_security_policy_supports_develop_and_promises_no_response_time() -> None:
    """Support the develop branch only and give no fixed response time."""
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    assert "develop" in text
    assert "pre-alpha" in text
    assert RESPONSE_TIME.search(text) is None


@pytest.mark.parametrize("form_name", ISSUE_FORMS)
def test_issue_form_has_required_keys_and_unique_ids(form_name: str) -> None:
    """Give each issue form the keys that GitHub requires."""
    form = load_yaml(ISSUE_TEMPLATE_DIR / form_name)
    assert form["name"]
    assert form["description"]
    assert form["body"]
    ids = []
    for element in form["body"]:
        assert element["type"] in FORM_ELEMENT_TYPES
        if element["type"] == "markdown":
            assert element["attributes"]["value"]
        else:
            assert element["attributes"]["label"]
            ids.append(element["id"])
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("form_name", "labels"),
    [
        ("bug.yml", {"bug", "needs-human"}),
        ("feature.yml", {"type:feature", "needs-human"}),
    ],
)
def test_issue_form_labels(form_name: str, labels: set[str]) -> None:
    """Label each form issue for triage by a person."""
    form = load_yaml(ISSUE_TEMPLATE_DIR / form_name)
    assert set(form["labels"]) == labels


def test_bug_form_links_security_policy_by_absolute_url() -> None:
    """Link the security policy from the bug form with an absolute URL."""
    form = load_yaml(ISSUE_TEMPLATE_DIR / "bug.yml")
    markdown_values = [
        element["attributes"]["value"]
        for element in form["body"]
        if element["type"] == "markdown"
    ]
    assert any(SECURITY_POLICY_URL in value for value in markdown_values)


def test_issue_chooser_turns_off_blank_issues_and_links_security() -> None:
    """Turn off blank issues and link the private vulnerability report."""
    chooser = load_yaml(ISSUE_TEMPLATE_DIR / "config.yml")
    assert chooser["blank_issues_enabled"] == "false"
    assert len(chooser["contact_links"]) == 1
    contact_link = chooser["contact_links"][0]
    assert contact_link["name"] == "Report a vulnerability"
    assert contact_link["url"] == ADVISORIES_URL
    assert contact_link["about"].strip()


def test_code_of_conduct_is_covenant_2_1_with_report_abuse_contact() -> None:
    """Use the Contributor Covenant 2.1 with the GitHub report abuse form."""
    text = CODE_OF_CONDUCT.read_text(encoding="utf-8")
    assert "version 2.1" in text
    assert REPORT_ABUSE_URL in text
    assert "[INSERT" not in text
    assert EMAIL.search(text) is None


def test_contributing_gives_setup_flow_and_changelog() -> None:
    """Give the setup link, the pull request flow, and the changelog rules."""
    text = CONTRIBUTING.read_text(encoding="utf-8")
    for expected in (
        "README.md#development",
        "develop",
        "changes/",
        *FRAGMENT_TYPES,
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
        "uv run towncrier build --draft",
        "skip-changelog",
    ):
        assert expected in text
    assert "sets up the changelog tool" not in text


def test_readme_names_changelog_check_preview_and_skip_link() -> None:
    """Name the changelog check, the preview command, and the skip rule link."""
    text = README.read_text(encoding="utf-8")
    for sentence in (
        "The Changelog workflow adds the `changelog` check."
        " It fails when a pull request adds no fragment in `changes/`.",
        "To preview the release notes, run `uv run towncrier build --draft`.",
        "To skip the check, see [Changelog](CONTRIBUTING.md#changelog).",
    ):
        assert sentence in text


def test_pull_request_template_shape() -> None:
    """Give the pull request template the Closes line, headings, and boxes."""
    lines = PULL_REQUEST_TEMPLATE.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# Closes: #"
    headings = [line.removeprefix("## ") for line in lines if line.startswith("## ")]
    assert headings == ["What's Changed", "User impact", "Test plan"]
    assert sum(line.startswith("- [ ] ") for line in lines) == 3
    assert not any("claude.ai" in line for line in lines)


@pytest.mark.parametrize("markdown_file", MARKDOWN_FILES)
def test_relative_links_resolve(markdown_file: str) -> None:
    """Point each relative link to a file that exists."""
    for target in relative_links(PROJECT_ROOT / markdown_file):
        assert target.exists(), f"{markdown_file} links to missing {target}"


@pytest.mark.parametrize("markdown_file", MARKDOWN_FILES)
def test_no_file_links_to_missing_architecture_doc(markdown_file: str) -> None:
    """Do not link to the architecture document, because it does not exist."""
    text = (PROJECT_ROOT / markdown_file).read_text(encoding="utf-8")
    assert "docs/architecture.md" not in text
