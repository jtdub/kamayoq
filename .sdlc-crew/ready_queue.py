"""Keep the status:ready label in step with the "Blocked by" lines of the issues.

An open issue that is not an epic is ready when every issue in its "Blocked by" line
is closed. The script adds the label to ready issues and removes it from the others.
It prints the changes and makes them only with --apply.
"""

import argparse
import json
import re
import subprocess

READY = "status:ready"
BLOCKED_BY = re.compile(r"^Blocked by (.+)$", re.MULTILINE)
ISSUE_REF = re.compile(r"#(\d+)")


def gh(*args: str) -> str:
    """Run gh and return its output."""
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def blockers(body: str) -> set[int]:
    """Return the issue numbers in the "Blocked by" line of an issue body."""
    match = BLOCKED_BY.search(body or "")
    return {int(n) for n in ISSUE_REF.findall(match.group(1))} if match else set()


def main() -> None:
    """Compare each issue with its blockers and fix the status:ready label."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="jtdub/kamayoq")
    parser.add_argument("--apply", action="store_true", help="Change the labels.")
    args = parser.parse_args()

    issues = json.loads(gh("issue", "list", "-R", args.repo, "--state", "all", "--limit", "1000",
                           "--json", "number,state,labels,body"))
    closed = {i["number"] for i in issues if i["state"] == "CLOSED"}
    for issue in sorted(issues, key=lambda i: i["number"]):
        labels = {label["name"] for label in issue["labels"]}
        ready = (issue["state"] == "OPEN" and "type:epic" not in labels
                 and blockers(issue["body"]) <= closed)
        if ready == (READY in labels):
            continue
        flag = "--add-label" if ready else "--remove-label"
        print(f"#{issue['number']}: {flag} {READY}")
        if args.apply:
            gh("issue", "edit", str(issue["number"]), "-R", args.repo, flag, READY)


if __name__ == "__main__":
    main()
