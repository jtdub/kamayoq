# AGENTS.md

Instructions for AI coding agents that work in this repository. Keep this file
short. Put the reason next to each rule.

## Project

<!-- One paragraph: what the app does and who uses it. -->

## Run and test

```bash
# start the app
<run command>
# run the tests
<test command>
```

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
