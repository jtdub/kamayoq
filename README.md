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

The Changelog workflow adds the `changelog` check. It fails when a pull request adds no fragment in `changes/`.
To preview the release notes, run `uv run towncrier build --draft`.
To skip the check, see [Changelog](CONTRIBUTING.md#changelog).

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

## Run the API server

Set `KAMAYOQ_DATABASE_URL` to a Postgres URL. Then run this command:

```bash
KAMAYOQ_DATABASE_URL=postgresql://kamayoq:CHANGE_ME@127.0.0.1:5432/kamayoq uv run kamayoq serve
```

The server listens on `http://127.0.0.1:8000`. Each log line on stderr is one JSON object.

### Settings

`KAMAYOQ_DATABASE_URL` is the only required setting. Each other setting has a default.

kamayoq reads the settings from environment variables. It also reads a TOML file, if `KAMAYOQ_CONFIG_FILE` gives its path.
Environment variables win over the TOML file. kamayoq does not read a `.env` file. [.env.example](.env.example) lists each variable.

WARNING: `KAMAYOQ_HOST=0.0.0.0` opens the server to the network, and the API has no login yet. Use it only in a container or behind a firewall.

| Environment variable | TOML key | Default | Meaning |
|---|---|---|---|
| `KAMAYOQ_DATABASE_URL` | `database_url` | None, required | The Postgres URL. The scheme is `postgres` or `postgresql`. |
| `KAMAYOQ_HOST` | `host` | `127.0.0.1` | The address that the server listens on. |
| `KAMAYOQ_PORT` | `port` | `8000` | The TCP port, from 1 to 65535. |
| `KAMAYOQ_READINESS_TIMEOUT` | `readiness_timeout` | `2.0` | The seconds that `/readyz` waits for Postgres. |
| `KAMAYOQ_LOG_LEVEL` | `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`, in upper or lower case. |
| `KAMAYOQ_API_DOCS` | `api_docs` | `false` | `true` shows `/docs`, `/redoc`, and `/openapi.json`. |
| `KAMAYOQ_CONFIG_FILE` | None | Not set | The path of the TOML file. A relative path starts at the current directory. |

Put `KAMAYOQ_DATABASE_URL` in the environment, not in the TOML file, because the URL can contain a password.
The TOML file uses top-level keys, with no table:

```toml
host = "127.0.0.1"
port = 8000
readiness_timeout = 2.0
log_level = "INFO"
api_docs = false
```

libpq reads the `PG*` environment variables and `~/.pgpass` for a part that the URL does not give, for example the password.
The URL must have a host. For a Unix socket, use `postgresql://user@localhost/db?host=/run/postgresql`.

### Endpoints

| Path | Status | Meaning |
|---|---|---|
| `/healthz` | 200 | The process runs. This endpoint does not connect to Postgres. |
| `/readyz` | 200 | Postgres answered `SELECT 1`. |
| `/readyz` | 503 | Postgres did not answer in time, refused the connection, or refused the login. |

`/readyz` runs one check at a time, and it keeps each result for 1 second.

### Exit codes

| Code | Meaning |
|---|---|
| 2 | A setting or the TOML file is not valid. The message names the setting, not its value. |
| 3 | The server cannot open the port, for example because the port is in use. |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request. All contributors follow the [Code of Conduct](CODE_OF_CONDUCT.md).
To report a vulnerability, follow [SECURITY.md](SECURITY.md). Do not open a public issue.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
