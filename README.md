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
The integration tests start a Postgres 18 container with pgvector and a Keycloak container, so they need Docker.
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

## Database

kamayoq needs Postgres 18 or later. The role in `KAMAYOQ_DATABASE_URL` must own the database or have the CREATE privilege on the `public` schema.

Run the migrations before you start the server for the first time, and after each upgrade of kamayoq:

```bash
KAMAYOQ_DATABASE_URL=postgresql://kamayoq:CHANGE_ME@127.0.0.1:5432/kamayoq uv run alembic upgrade head
```

The first migration creates the `organizations` table and one organization with the name `default`. Do not delete the `default` organization. kamayoq does not prevent this delete yet.

When a setting is missing or not valid, the command prints one line that starts with `FAILED: Settings are not valid:`, then the name of each bad setting. The exit status is 255.

WARNING: `alembic downgrade base` deletes all kamayoq data. Make a backup before you run it.

```bash
KAMAYOQ_DATABASE_URL=postgresql://kamayoq:CHANGE_ME@127.0.0.1:5432/kamayoq uv run alembic downgrade base
```

### Add a table

Follow these rules for each new model:

1. Inherit `OrgScoped`. It adds `id`, `created_at`, `updated_at`, and `org_id`.
2. Add `Classified` to a table that holds content. It adds `data_class`, with no default.
3. If the table holds no content, add the table name and the reason to `UNCLASSIFIED_TABLES` in `kamayoq.db.base`.
4. Include `org_id` in each unique constraint.
5. Put the model in `kamayoq.db.models`, or import it there.
6. Start an empty Postgres 18 database for development.
7. Set `KAMAYOQ_DATABASE_URL` to that database.
8. Run `uv run alembic upgrade head`. The database then has the schema of the last migration.
9. Run `uv run alembic revision --autogenerate -m "<message>"`. Alembic compares the models with the database and writes the new file.
10. Remove the `# ###` comment lines from the new file. The pre-commit hooks reject them.
11. Read the new file.
12. Run `uv run pytest`.

The tests fail when a model has no valid `org_id`, or has no `data_class` and is not in `UNCLASSIFIED_TABLES`.

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

WARNING: `KAMAYOQ_HOST=0.0.0.0` opens the server to the network. Set the OIDC settings before you use it. See [Sign in](#sign-in).

| Environment variable | TOML key | Default | Meaning |
|---|---|---|---|
| `KAMAYOQ_DATABASE_URL` | `database_url` | None, required | The Postgres URL. The scheme is `postgres` or `postgresql`. |
| `KAMAYOQ_HOST` | `host` | `127.0.0.1` | The address that the server listens on. |
| `KAMAYOQ_PORT` | `port` | `8000` | The TCP port, from 1 to 65535. |
| `KAMAYOQ_READINESS_TIMEOUT` | `readiness_timeout` | `2.0` | The seconds that `/readyz` waits for Postgres. |
| `KAMAYOQ_LOG_LEVEL` | `log_level` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`, in upper or lower case. |
| `KAMAYOQ_API_DOCS` | `api_docs` | `false` | `true` shows `/docs`, `/redoc`, and `/openapi.json`. |
| `KAMAYOQ_PLUGINS` | `plugins` | Not set | The plugins to load, as a comma list of `group:name`. See [Plugins](#plugins). |
| `KAMAYOQ_OIDC_ISSUER` | `oidc_issuer` | Not set | The issuer URL of the OIDC provider. It must use `https`, or `http` on `localhost`, `127.0.0.1`, or `[::1]`. Set it together with `KAMAYOQ_OIDC_AUDIENCE`. Checked at start. |
| `KAMAYOQ_OIDC_AUDIENCE` | `oidc_audience` | Not set | The audience that an access token must have. Set it together with `KAMAYOQ_OIDC_ISSUER`. Checked at start. |
| `KAMAYOQ_OIDC_GROUPS_CLAIM` | `oidc_groups_claim` | `groups` | The token claim that holds the groups of the user. Checked at start. |
| `KAMAYOQ_OIDC_ROLE_MAP` | `oidc_role_map` | Not set | A JSON object of IdP group to list of kamayoq roles. See [Roles](#roles). Checked at start. |
| `KAMAYOQ_SECRETS_BACKEND` | `secrets_backend` | `env` | Where kamayoq reads secrets: `env` or `file`. See [Secrets](#secrets). |
| `KAMAYOQ_SECRETS_DIR` | `secrets_dir` | `/run/secrets` | The directory of the secret files. It must exist when `KAMAYOQ_SECRETS_BACKEND` is `file`. |
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

### Plugins

A plugin is a class in a Python package that adds a runtime, a channel, or another part to kamayoq.
kamayoq has no plugin groups yet. The Protocol issues add them.

WARNING: A plugin runs in the kamayoq process with the same access as kamayoq. Add only a package that you trust.

To allow plugins, list each one as `group:name` in `KAMAYOQ_PLUGINS`:

```bash
KAMAYOQ_PLUGINS=runtimes:langgraph,channels:slack
```

In the TOML file, use an array: `plugins = ["runtimes:langgraph", "channels:slack"]`. A TOML string uses the same comma form.

When two packages declare the same plugin, the start stops.
If the real package is not installed, another package can declare its name. The `Loaded plugin` log line names the package that kamayoq loaded.
kamayoq does not import an installed plugin that the list does not name, and it writes one log line for it.

These start errors give exit code 4:

- An entry names a group that does not exist.
- No installed package declares the plugin.
- Two packages declare the plugin.
- The plugin does not load.
- The class does not match the Protocol of its group.

A package declares a plugin as an entry point in its `pyproject.toml`:

```toml
[project.entry-points."kamayoq.runtimes"]
langgraph = "kamayoq_langgraph:LangGraphRuntime"
```

kamayoq checks each plugin at start:

- The entry point names a class.
- The class defines each member of the Protocol.
- An `async` method stays `async`.
- The parameter names are the same, and in the same order.

Declare a data member as a class attribute or an annotation, not only in `__init__`.
kamayoq does not check annotations at start, so run mypy against the Protocol.

### Secrets

A component asks for a secret with a secret reference, for example `secret://slack_token`.
The name after `secret://` has lower-case letters, digits, and `_`. It starts with a letter and has 1 to 128 characters.

`KAMAYOQ_SECRETS_BACKEND` selects where kamayoq reads the value:

- `env`, the default: kamayoq reads `secret://slack_token` from the variable `KAMAYOQ_SECRET_SLACK_TOKEN`. The variable name is the secret name in upper case.
- `file`: kamayoq reads `secret://slack_token` from the file `/run/secrets/slack_token`, as Docker mounts a secret. `KAMAYOQ_SECRETS_DIR` changes the directory.

For example, set the Slack token in the environment of `kamayoq serve`:

```bash
KAMAYOQ_SECRET_SLACK_TOKEN=CHANGE_ME uv run kamayoq serve
```

The file backend removes one line end from the end of the file, and keeps all other content.
A secret file must be a regular file of at most 64 KiB in UTF-8, inside the secrets directory.
An empty variable or an empty file is the same as a missing secret.
kamayoq reads the value at each use, so a changed value takes effect with no restart.

Log lines show `**********` in place of each secret value that kamayoq knows.
kamayoq knows each value that it reads. With the `env` backend, it also knows each `KAMAYOQ_SECRET_` value at start.
At start, kamayoq knows the password in `KAMAYOQ_DATABASE_URL`, in the URL form and in the decoded form.
Code in kamayoq can call `kamayoq.secrets.redact(text)` to hide the known values in other text.

These limits apply:

- kamayoq cannot hide a value that it did not read, or a changed form of a value, for example base64.
- A value of fewer than 4 characters, or of white space only, is not hidden. kamayoq writes one warning for each secret. The warning names the secret and does not show the value.
- A password from `PGPASSWORD` or `~/.pgpass` is not hidden.
- Output that does not go through the kamayoq log handler is not hidden: a logger with `propagate=False`, a crash traceback, `print`, `warnings`, and output before the log setup.
- Each process that can read the environment of kamayoq can read an `env` secret. Use the `file` backend to keep secrets out of the environment.

### Sign in

Each route under `/v1` needs an OIDC access token, except `/v1/auth/config`. Send the token in the `Authorization: Bearer <token>` header.
Set `KAMAYOQ_OIDC_ISSUER` and `KAMAYOQ_OIDC_AUDIENCE` to turn on sign-in. Without them, the server starts, writes one warning, and each `/v1` route returns 401.

The API checks these items of each token:

- The signature, with a key from the `jwks_uri` of the issuer. The algorithm must be RS256, RS384, RS512, PS256, ES256, or ES384.
- The `iss` claim is equal to `KAMAYOQ_OIDC_ISSUER`, and the `aud` claim has `KAMAYOQ_OIDC_AUDIENCE`.
- The `exp`, `nbf`, and `iat` claims, with 60 seconds of clock difference. The token must have `exp` and `sub`.

A token that is missing or not valid gets 401 with a `WWW-Authenticate: Bearer` header. When the OIDC provider does not give its keys, the API returns 503.
After a failed request to the provider, kamayoq waits 30 seconds before it sends the next one.

To set up Keycloak:

1. Make a realm, for example `kamayoq`.
2. Make a client, for example `kamayoq-cli`. Turn off "Client authentication". Turn on "OAuth 2.0 Device Authorization Grant".
3. Open the dedicated client scope of the client. Add an "Audience" mapper. Set "Included Custom Audience" to the value of `KAMAYOQ_OIDC_AUDIENCE`, for example `kamayoq-api`.
4. Add a "Group Membership" mapper to the same scope. Set "Token Claim Name" to `groups`, and turn on "Add to access token".
5. Set `KAMAYOQ_OIDC_ISSUER=https://<keycloak host>/realms/kamayoq` and `KAMAYOQ_OIDC_AUDIENCE=kamayoq-api`.

The `kamayoq login` command comes in a later release. To test the setup now, get a token with the password grant of a test client:

1. Turn on "Direct access grants" on the client. Use a test client only, because this grant sends the user password to the client.
2. Get a token for a test user, and call `/v1/me` with it:

```bash
TOKEN=$(curl -s -d grant_type=password -d client_id=kamayoq-cli \
  -d username=<user> -d password=<password> \
  https://<keycloak host>/realms/kamayoq/protocol/openid-connect/token | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/v1/me
```

Use these values for each provider. Issue [#93](https://github.com/jtdub/kamayoq/issues/93) has the full Entra ID and Okta steps.

| Provider | `KAMAYOQ_OIDC_ISSUER` | `KAMAYOQ_OIDC_AUDIENCE` | `KAMAYOQ_OIDC_GROUPS_CLAIM` | CLI scopes |
|---|---|---|---|---|
| Keycloak | `https://<host>/realms/<realm>` | The value of the audience mapper | `groups`, with the full group path, for example `/kamayoq-admins` | `openid offline_access` |
| Entra ID | `https://login.microsoftonline.com/<tenant-id>/v2.0`. `<tenant-id>` is the directory (tenant) ID, a GUID. Do not use a domain name. | The application ID of the API app. Set `api.requestedAccessTokenVersion: 2` in its manifest (`accessTokenAcceptedVersion` in the old manifest). | `groups`. The values are group object IDs. Add the groups claim in Token configuration of the API app first. | `openid offline_access api://<app-id>/<scope>` |
| Okta | `https://<org>.okta.com/oauth2/<server-id>`, from a custom authorization server | The audience of the authorization server | The groups claim that you add to the authorization server | `openid offline_access` |

Limits:

- A revoked token stays valid until it expires. kamayoq does not ask the provider about each token.
- Each server process loads and keeps its own copy of the provider keys.
- kamayoq keeps the loaded keys for up to 24 hours while the provider is down. During that time, the `/v1` routes still accept valid tokens.
- The `/v1` routes return 503 only when kamayoq has no keys, for example after 24 hours, or after a restart during the outage. `/readyz` stays 200.
- WARNING: A restart of kamayoq while the provider is down deletes the loaded keys, and each `/v1` route then returns 503. Do not restart kamayoq until the provider is up again.

### Roles

`KAMAYOQ_OIDC_ROLE_MAP` gives kamayoq roles to the members of IdP groups. The roles are `admin`, `agent-author`, `tool-granter`, `approver`, `auditor`, and `viewer`.
A user gets each role of each group of the token that the map names. A user with no mapped group gets no role. `/v1/me` shows the roles.
No route checks the roles in this release. Issue [#52](https://github.com/jtdub/kamayoq/issues/52) adds the permission checks.

In the environment, give a JSON object:

```bash
KAMAYOQ_OIDC_ROLE_MAP='{"/kamayoq-admins": ["admin"], "/kamayoq-readers": ["viewer"]}'
```

In the TOML file, give an inline table:

```toml
oidc_role_map = { "/kamayoq-admins" = ["admin"], "/kamayoq-readers" = ["viewer"] }
```

Use the group names as the token gives them. Keycloak gives the full group path, for example `/kamayoq-admins`. Entra ID gives group object IDs.
A role name that does not exist, an empty group name, or text that is not a JSON object stops `kamayoq serve` with exit code 2.

### Endpoints

| Path | Status | Meaning |
|---|---|---|
| `/healthz` | 200 | The process runs. This endpoint does not connect to Postgres. |
| `/readyz` | 200 | Postgres answered `SELECT 1`. |
| `/readyz` | 503 | Postgres did not answer in time, refused the connection, or refused the login. |
| `/v1/me` | 200 | The token is valid. The body has the `subject`, the `issuer`, the `groups`, and the kamayoq `roles` of the token. |
| `/v1/me` | 401 | The token is missing or not valid, or the server has no OIDC settings. |
| `/v1/me` | 503 | The OIDC provider did not give its signing keys. |

`/readyz` runs one check at a time, and it keeps each result for 1 second.

### Exit codes

| Code | Meaning |
|---|---|
| 2 | A setting or the TOML file is not valid. The message names the setting. It shows no value, except the bad entries of `KAMAYOQ_PLUGINS`. |
| 3 | The server cannot open the port, for example because the port is in use. |
| 4 | A plugin on the allowlist cannot load, or does not match its Protocol. The message names each plugin. |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you open a pull request. All contributors follow the [Code of Conduct](CODE_OF_CONDUCT.md).
To report a vulnerability, follow [SECURITY.md](SECURITY.md). Do not open a public issue.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
