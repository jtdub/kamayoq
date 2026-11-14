# Contributing to kamayoq

Thank you for your help. This file tells you how to make a change to kamayoq.

## Before you start

- Read the [Code of Conduct](CODE_OF_CONDUCT.md). All contributors follow it.
- Do not report a vulnerability in an issue. Follow the [security policy](SECURITY.md).
- Before a large change, open an issue with a form. Agree on the change before you write the code.

## Set up

Follow the [Development](README.md#development) section of the README.
It gives the uv version, the install commands, and the test commands.

## Make a change

1. Make a branch from `develop`.
2. Write a test for each change in behavior.
3. Run the checks:

   ```bash
   uv run pre-commit run --all-files
   uv run pytest
   ```

4. Open one pull request for each change. The pull request merges into `develop`.

## Changelog

Add a changelog fragment for each change that a user can see.

- Name the file `changes/<issue>.<type>`.
  Use the pull request number when no issue exists.
- Use one of these types: `added`, `changed`, `fixed`, `removed`, or `security`.
- Write one item on each line. Do not add a bullet marker.
- Start each item with a verb, for example "Added" or "Fixed".
- To preview the release notes, run `uv run towncrier build --draft`.
- The `changelog` check fails when a pull request adds no fragment.
- When a change has nothing for a user to see, ask the maintainer to add the `skip-changelog` label.
- Pull requests from Dependabot skip the check.

## Pull request

- Fill in the pull request template.
- On the first line, write `# Closes: #<n>`, where `<n>` is the issue number.
  Write `# Closes: DNE` when no issue exists.
- Make sure that CI passes. The maintainer reviews the pull request after that.

## Architecture

Issue [#2](https://github.com/jtdub/kamayoq/issues/2) holds the architecture of kamayoq.

## AI agents

AI coding agents follow [AGENTS.md](AGENTS.md).
