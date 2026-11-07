# dSentry

<p align="center">
  <img src="hub/ui/public/logo.png" width="240" alt="dSentry logo" />
</p>

<p align="center">
  <a href="https://github.com/unikii/dsentry/actions/workflows/build-docker.yml"><img src="https://github.com/unikii/dsentry/actions/workflows/build-docker.yml/badge.svg?branch=master" alt="CI status" /></a>
  <a href="https://github.com/unikii/dsentry/actions/workflows/codeql.yml"><img src="https://github.com/unikii/dsentry/actions/workflows/codeql.yml/badge.svg?branch=master" alt="CodeQL status" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-blue.svg" alt="License: Apache-2.0" /></a>
</p>

Self-hosted monitoring for the health of your hard drives and SSDs.

dSentry has two parts:

- `dsnode` runs on each machine and reads SMART data with `smartctl`.
- The hub stores the data and provides the web dashboard, events, and alerts.

The hub uses SQLite for account and device data and VictoriaMetrics for metrics.

## Features

- Monitor NVMe, SATA, SCSI/SAS, USB, and some MegaRAID devices.
- View temperature, wear, error counts, SMART status, and historical charts.
- Keep raw `smartctl` output for troubleshooting.
- Track SMART failures, recoveries, and threshold events.
- Monitor multiple machines from one hub.
- Send alerts through email, Discord, Telegram, Slack, and other Apprise services.
- Run one private instance or enable multi-user OAuth mode.
- Use the dashboard in English, Simplified Chinese, Traditional Chinese, or
  Spanish.

## Try It

A shared demo may be available at [dsentry.waredb.com](https://dsentry.waredb.com/).
It is a small, shared server with no uptime or data-retention guarantee. For
anything important, run your own hub.

## Quick Start

### Requirements

- Docker and the Docker Compose plugin for the hub.
- `smartmontools` on every machine monitored by `dsnode`.
- Git.
- Python 3.11+ and Go 1.26.10+ only when building the hub or node from source.

### Start the hub

```bash
git clone https://github.com/unikii/dsentry.git
cd dsentry
cp .env.example .env
docker compose up -d --build
```

This builds the API and UI from source. To use the published release images
instead, run `docker compose pull` and `docker compose up -d`.

Open the dashboard at <http://localhost:3000>.

The API is available at <http://localhost:9090>; its interactive API docs are
at <http://localhost:9090/docs>. VictoriaMetrics listens on `localhost:8428`.

The Compose file binds these ports to loopback only. For access from another
machine, put the hub behind an HTTPS reverse proxy. See [Reverse Proxy](#reverse-proxy).
The UI container already includes nginx and proxies `/api` to the API, so no
extra web server is needed for local use.

### Private mode

Private mode is the default and is intended for one owner. On a new database it
creates the local `admin` account without a password. This is convenient for a
local setup, but set a password in **Settings** before making the dashboard
reachable from the internet.

The passwordless bootstrap only happens when the users table is empty. Once a
password is set, it is required for sign-in.

### Public mode

Public mode supports multiple users and is **OAuth-only**: usernames and
passwords are not accepted at sign-in. Users authenticate with GitHub, Google,
or both, and their account is created automatically on first sign-in. Set these
values in `.env` before starting the hub:

```dotenv
RUN_MODE=public
OAUTH_ALLOWED_ORIGINS=https://demosentry.example.com
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
```

You can configure GitHub, Google, or both OAuth providers. The redirect origin
must exactly match the address used to open the dashboard. Register
`https://<your-host>/oauth/callback/github` and
`https://<your-host>/oauth/callback/google` as the callback URLs in each
provider.

Password login, password changes in **Settings**, and the `scripts/users.sh
create` / `set-password` commands are disabled in public mode. `list`, `enable`,
and `disable` still work for OAuth-created accounts.

### Use pre-built images

`docker-compose.yml` contains the build definitions and also defaults to the
published GHCR images. Pull and run the release images with:

```bash
docker compose pull
docker compose up -d
```

Set `API_IMAGE` and `UI_IMAGE` to pin a release or use images from a fork:

```bash
export API_IMAGE=ghcr.io/unikii/dsentry/dsentry-api:v0.1.0
export UI_IMAGE=ghcr.io/unikii/dsentry/dsentry-ui:v0.1.0
docker compose pull
docker compose up -d
```

The UI is served on `127.0.0.1:3000`. Set `UI_PORT` to use another host port:

```bash
export UI_PORT=80
docker compose up -d
```

Images are published for `linux/amd64` and `linux/arm64`. `latest` tracks the
default branch; pin a `vX.Y.Z` tag for production. To upgrade:

```bash
docker compose pull
docker compose up -d
```

Back up `data/` first if a release changes the database.

## Releases

Pushing a SemVer tag such as `v0.1.0` triggers:

- `release-dsnode.yml`, which builds the node binaries, writes `.sha256`
  files, and creates the GitHub Release with signed build provenance
  attestations.
- `build-docker.yml`, which runs the test suites and publishes multi-arch API
  and UI images to GitHub Container Registry with SBOM and provenance
  attestations.

The project uses [Semantic Versioning](https://semver.org/). GitHub generates
release notes from merged changes.

## Add a Machine

1. Open **Nodes** and choose **Add Node**.
2. Copy the push key and install `dsnode` on the machine with the drives.
3. The node appears as soon as it registers (on first start), before its
   first scan completes.

The installer downloads the latest tagged release, checks its SHA-256 file, and
registers the node. Set `GITHUB_REPO` to the repository that owns your releases.
The examples below use the current `master` branch; change it if you rename
your default branch.

### Linux and macOS

```bash
export GITHUB_REPO=unikii/dsentry
curl -fsSL "https://raw.githubusercontent.com/${GITHUB_REPO}/master/scripts/install.sh" \
  | sudo GITHUB_REPO="$GITHUB_REPO" sh -s -- \
      "https://hub.example.com/api" "your-push-key"
```

The installer needs root and `smartctl` on `PATH`.

### Windows

Run PowerShell as Administrator:

```powershell
$env:GITHUB_REPO = "unikii/dsentry"
$env:API_ENDPOINT = "https://hub.example.com/api"
$env:PUSH_KEY = "your-push-key"
iwr -useb "https://raw.githubusercontent.com/$env:GITHUB_REPO/master/scripts/install.ps1" | iex
```

### Run the binary directly

```bash
dsnode --api-endpoint https://hub.example.com/api --push-key your-push-key
```

If you expose the API directly on port `9090` instead of running it behind
the `/api` reverse proxy, use `http://hub.example.com:9090` as the endpoint.

`dsnode` needs `smartctl` on the monitored machine. Its configuration is kept
next to the binary in `dsnode.toml` and `dsnode.json`.

## Configuration

Copy `.env.example` to `.env`. The most useful settings are:

| Setting | Purpose |
|---|---|
| `RUN_MODE` | `private` for one local owner with password sign-in, or `public` for OAuth-only multi-user sign-in. |
| `APP_VERSION` | Version string reported by the API (default `0.1.0`). |
| `API_DOCS_ENABLED` | Set `false` to disable `/docs`, `/redoc`, and `/openapi.json`. |
| `JWT_SECRET` | Secret used to sign login sessions. It is generated into `data/jwt_secret` when empty. |
| `VICTORIAMETRICS_URL` | VictoriaMetrics HTTP endpoint (default `http://localhost:8428`). |
| `VICTORIAMETRICS_USERNAME` / `VICTORIAMETRICS_PASSWORD` | Optional basic auth for VictoriaMetrics. |
| `VICTORIAMETRICS_RETENTION` | Retention passed to `-retentionPeriod`; a bare number means months, or use `24h`, `1y`, `100y`, etc. Minimum is 24h/1d. |
| `GLOBAL_PUSH_INTERVAL` | How often nodes send metrics, in minutes. |
| `LATEST_METRICS_LOOKBACK_HOURS` | Lookback for the dashboard's latest-sample query (1-720, default 48). |
| `GLOBAL_DEVICE_PER_NODE` | Soft per-push device limit; it does not cap lifetime registrations. |
| `GLOBAL_RAW_PUSH_BASE` | Raw output schedule: `day`, `push`, or `never`. |
| `SMTP_URL` | SMTP connection used by email alerts. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins; set this explicitly for a public deployment. |
| `TRUST_PROXY_HEADERS` | Trust `X-Forwarded-For` / `X-Real-IP` from the reverse proxy; keep `true` behind a TLS proxy. |
| `OAUTH_ALLOWED_ORIGINS` | Origins allowed to complete OAuth login. Required in public mode. |
| `ALERT_ALLOW_PRIVATE_TARGETS` | Set `true` only when this trusted instance must alert a private-network service such as Gotify. |

The complete list is in `.env.example`. OAuth credentials belong in `.env`, not
in the repository.

### User management

There is no user-management page. Run the helper from the host:

```bash
./scripts/users.sh list
./scripts/users.sh create alice
./scripts/users.sh set-password alice
./scripts/users.sh disable alice
```

`create` and `set-password` are private-mode only. In public mode, accounts are
created on first OAuth sign-in; `list`, `enable`, and `disable` still work.

## Data and Backups

The `data/` directory contains the SQLite database, VictoriaMetrics files, and
the generated JWT secret. Keep it outside version control and back it up as one
unit.

If `data/jwt_secret` is lost, existing browser sessions stop working. For a
consistent VictoriaMetrics backup, use its snapshot API or stop the container
before copying `data/victoriametrics`.

## Reverse Proxy

The UI image serves the dashboard and proxies `/api/*` to the API, so the proxy
only has to terminate TLS and forward the whole hostname to the UI port. By
default, that is `http://127.0.0.1:3000`. If you set `UI_PORT`, forward to that
port instead.

For example, with Caddy:

```caddyfile
hub.example.com {
	reverse_proxy 127.0.0.1:3000
}
```

Or with Nginx:

```nginx
server {
	listen 443 ssl;
	server_name hub.example.com;

	location / {
		proxy_pass http://127.0.0.1:3000;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
	}
}
```

You can also route `/api/*` straight to `127.0.0.1:9090`, but then the proxy must
strip the `/api` prefix (the API routes have no prefix).

Use HTTPS for a public hub. Do not use `--insecure` on `dsnode` unless this is a
deliberate, isolated test.

## Development

### Backend

```bash
cd hub/api
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python -m pytest -v
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 9090 --reload
```

### Frontend

```bash
cd hub/ui
pnpm install --frozen-lockfile
cp .env.example .env
pnpm dev
```

Before committing UI changes, run:

```bash
pnpm check
pnpm test
```

### dsnode

```bash
cd node
go test ./...
go vet ./...
go build -o dsnode .
```

## Project Layout

```text
hub/api/                 FastAPI backend
hub/ui/                  React and TypeScript dashboard
node/                    dsnode Go agent
schemas/                 SQLite and metrics schemas
scripts/                 Installers and administration helpers
.github/                 CI workflows, CodeQL config, and Dependabot
docker-compose.yml       Build or pull the hub stack
```

## Credits

SMART attribute metadata, thresholds, and test fixtures are derived from
[Scrutiny](https://github.com/AnalogJ/scrutiny), an MIT-licensed SMART
monitoring project by Jason Kulatunga. The full license text is in
[`NOTICE`](NOTICE).

## Troubleshooting

### VictoriaMetrics cannot write its data directory

The official VictoriaMetrics container runs as root and creates
`data/victoriametrics` on first start. If you run the image as a non-root user
or use rootless Docker, make sure that directory is writable by that user:

```bash
sudo chown -R 1000:1000 data/victoriametrics
```

Do not chown the whole `data/` tree just for VictoriaMetrics — the API has its
own UID requirement documented below.

### API container cannot create the SQLite database

The API image runs as the unprivileged `dsentry` user (UID 10001). When using
the bind-mounted `./data` directory, make it writable by that UID:

```bash
sudo chown -R 10001:10001 data
```

Keep `data/` private (`chmod 700`) — it contains push keys, password hashes,
alert targets, and the JWT secret.

## Security

### Reporting a vulnerability

Please do **not** open a public issue for a security problem. Report it
privately through GitHub's **Security → Advisories → Report a vulnerability**
flow for this repository. Include:

- affected version or commit,
- a minimal reproduction,
- the impact you observed,
- any suggested fix.

You can expect an initial response within a few days. Please give the project
time to ship a fix before publishing details.

Security fixes are applied to the latest release and the `master` branch;
older releases may not receive backports.

### Deployment notes

- Use HTTPS for any hub reachable outside a trusted network. The Compose files
  bind the API, UI, and VictoriaMetrics ports to `127.0.0.1`; see
  [Reverse Proxy](#reverse-proxy).
- In `private` mode the bootstrap `admin` account has no password until one is
  set in **Settings**. Set one before exposing the dashboard.
- In `public` mode sign-in is OAuth-only. Local password login, password
  changes in **Settings**, and the CLI password commands are disabled; users
  are created on their first OAuth sign-in.
- Set `CORS_ALLOWED_ORIGINS` and `OAUTH_ALLOWED_ORIGINS` explicitly for a
  public deployment, and keep `TRUST_PROXY_HEADERS=true` only when the API is
  reachable exclusively through a reverse proxy.
- Leave `ALERT_ALLOW_PRIVATE_TARGETS=false` unless this is a trusted instance
  that must send alerts to a private-network service.
- Treat `data/` and `dsnode.json` (which contains the node push key) as
  secrets, and back up `data/` as one unit.

## Contributing

Contributions are welcome. Open an issue or pull request. For security issues,
do not open a public issue; use GitHub's private vulnerability reporting flow.

## License

Apache-2.0. See [LICENSE](LICENSE). Third-party notices are in
[NOTICE](NOTICE).
