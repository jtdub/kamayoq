# kamayoq

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

kamayoq is an open-source control plane for agentic operations. It runs AI agents
under policy, sends each tool call through one gateway, and keeps an audit record
of each action.

## Status

Pre-alpha. Under design. Not ready for use. See the roadmap in [#10](https://github.com/jtdub/kamayoq/issues/10).

## Components

| Name | What it does |
|---|---|
| kamayoq | The control plane defines agents, runs them, and applies policy and approvals. |
| tambo | The MCP gateway checks scopes, injects secrets, and applies rate limits for each agent tool call. |
| quipu | The audit store writes a hash-chained, append-only record of prompts, tool calls, decisions, and results. |

## What kamayoq is not

- Not an agent framework. kamayoq runs agents on adapters, with LangGraph as the default.
- Not a model provider or an LLM proxy. It calls providers through the LiteLLM SDK, with no proxy.
- Not a multi-tenant SaaS. It is single-tenant and self-hosted.
- Not an install guide. Install steps come with the deployment work.

## Documentation

- Requirements: [#1](https://github.com/jtdub/kamayoq/issues/1)
- Architecture: [#2](https://github.com/jtdub/kamayoq/issues/2)
- Roadmap: [#10](https://github.com/jtdub/kamayoq/issues/10)

## Development

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.11.33 or a later 0.11 release.
The latest uv release and a plain `uv self update` give a uv that is too new, and `uv sync` stops.
To install uv 0.11.33 with the standalone installer, run this command:

```bash
curl -LsSf https://astral.sh/uv/0.11.33/install.sh | sh
```

To change a uv that the standalone installer installed, run `uv self update 0.11.33`.
uv installs Python 3.12 when your machine does not have it.

```bash
uv sync
uv run pre-commit install
uv run kamayoq --version
uv run pytest
```

`uv run pytest` runs the unit tests and the integration tests, and prints a coverage report.
The integration tests start a Postgres 18 container with pgvector, so they need Docker.
When Docker is not available, pytest skips them and shows the reason.
If `KAMAYOQ_REQUIRE_DOCKER` has a value other than empty or `0`, the tests fail and do not skip.
To run one group only:

```bash
uv run pytest -m unit
uv run pytest -m integration
```

While the tests run, the test containers publish their ports on all network interfaces.
To publish on `127.0.0.1` only, set `"ip": "127.0.0.1"` in the Docker daemon settings. This setting changes every container on your machine, not only tests. The project did not test this setting.

The pre-commit hooks run ruff, mypy, and a check for prose comments before each commit.
To run the same checks by hand:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pre-commit run --all-files
```

### Continuous integration

Each pull request to `develop` and each push to `develop` runs the three checks of the CI workflow:

- `lint` runs `ruff check`, `ruff format --check`, and the check for prose comments.
- `types` runs `mypy`.
- `tests` runs `pytest` with the unit tests, the integration tests, and coverage.

The checks run the commands of the blocks above.
The `tests` check sets `KAMAYOQ_REQUIRE_DOCKER=1`, so a missing Docker fails the check.
Each value except empty and `0` requires Docker.
To get the same behavior on your machine, run `KAMAYOQ_REQUIRE_DOCKER=1 uv run pytest`.

The Supply chain workflow adds two checks. See [Supply chain](#supply-chain).

### Supply chain

Each pull request to `develop`, each push to `develop`, and a daily schedule run the Supply chain workflow:

- `audit` runs `pip-audit` with the OSV database on each package in `uv.lock`. OSV holds known vulnerabilities and known malicious releases.
- `sbom` writes a CycloneDX 1.5 SBOM of each package in `uv.lock`. Download it as the `sbom-cyclonedx` artifact of the run.

uv installs only the files in `uv.lock`, and it checks the sha256 hash of each file. CI sets `UV_LOCKED=1`, so a lock that does not match `pyproject.toml` fails the run.

uv does not lock a release that is less than 7 days old (`exclude-newer = "7 days"` in `pyproject.toml`). Dependabot opens update pull requests each week for Python packages and GitHub Actions, and it also waits 7 days after each release. Each Action is pinned by commit SHA, with the version in a comment.

To add a fix that is less than 7 days old:

1. Add `exclude-newer-package = { <name> = "0 days" }` under `[tool.uv]` in `pyproject.toml`.
2. Run `uv lock --upgrade-package <name>`.
3. Open an issue to remove the entry after 7 days.

When `audit` reports a vulnerability that has no fixed release:

1. Add `--ignore-vuln <ID>` to the `pip-audit` command in `.github/workflows/supply-chain.yml`.
2. Make the same change in `tests/test_supply_chain.py`.
3. Give the reason in the pull request.
4. Open an issue to remove the flag.

GitHub sends a notice of a failed daily run to the user who last changed the schedule, if that user's Actions notifications are on. GitHub turns the schedule off after 60 days with no activity in the repository. To turn it on again, run `gh workflow enable supply-chain.yml`.

Dependabot runs uv 0.11. If its log at Insights > Dependency graph > Dependabot shows a uv version error, update `required-version` in `pyproject.toml`.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
