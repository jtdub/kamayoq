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

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) 0.10.7 or a later 0.10 release.
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

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
