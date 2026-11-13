# AGENTS.md

Instructions for AI coding agents that work in this repository. Keep this file
short. Put the reason next to each rule.

## Project

<!-- One paragraph: what the app does and who uses it. -->

## Run and test

```bash
# install the package and the dev tools
uv sync
# show the version
uv run kamayoq --version
# run the tests
uv run pytest
# run each check alone
uv run ruff check
uv run ruff format --check
uv run mypy
# run all checks, as the commit hook does
uv run pre-commit run --all-files
```

- Run `uv run pre-commit install` once in each clone. The hooks then run before each
  commit.

## Rules

- Make the smallest change that solves the problem. A small change is easy to review
  and easy to undo.
- Write a test for each change in behavior. The test is the proof that it works.
- Never commit a secret. Read secrets from environment variables. `.env.example` lists
  the names.
- Open a pull request for each change. Do not push to the default branch.
- Before an action that deletes data or costs money, state the risk and ask.

## Workflow

This repository uses `sdlc-crew`. Start a change with `/sdlc-crew "<what you want>"`.
The config is in `.sdlc-crew.yaml`.
