# Swarm Labs — Plane fork deployment pipeline

How our customised Plane stays in sync with upstream while carrying our own
changes, and how those changes reach the live server at
**https://projects.swarmlabs.io**.

## Branches

| Branch       | Role                                                                          |
| ------------ | ----------------------------------------------------------------------------- |
| `main`       | Clean mirror of an upstream **release tag**. Force-updated, never hand-edited. |
| `swarm-prod` | `main` + our custom commits + this pipeline. **Default branch.** Built & deployed. |
| `upstream`   | git remote → `makeplane/plane` (source of new tags).                          |

Our changes (e.g. the guest-visibility patch from issue #1) live only on
`swarm-prod`, each marked `# GUEST-VISIBILITY FORK`, and are rebased onto `main`
on every upstream upgrade.

## What gets built

Our changes are **API-only**, so the pipeline rebuilds **just one image** —
`ghcr.io/swarmlabs-io/plane-backend` (used by the `api`, `worker`, `beat-worker`
and `migrator` services). The `web`, `space`, `admin`, `live` and `proxy` images
keep coming straight from `makeplane`. The 950 MB server never builds anything.

## The three flows

### 1. Track upstream — `swarm-upstream-watch.yml` (weekly, semi-auto)

Detects a new stable tag → force-updates `main` → rebases `swarm-prod` on a temp
branch → opens an **"Upgrade to Plane vX.Y.Z"** PR if clean, or pings Slack if it
conflicts. A human reviews/merges. Never self-merges.

### 2. Build — `swarm-build-deploy.yml` (on push to `swarm-prod`)

Builds `apps/api/Dockerfile.api` (context `./apps/api`) and pushes two tags:
`:swarm-prod` (moving) and `:<upstream-tag>-swarm.<sha>` (immutable, used for the
actual deploy + rollback).

### 3. Deploy — same workflow, `deploy` job (gated)

Runs only after the `production` environment's **required reviewer approves** in
the Actions tab. SSHes to the server, ships `deploy.sh`, which pins the new tag in
`plane.env`, pulls, runs migrations, and recreates the four backend services.

## Server config

`/opt/plane-selfhost/plane-app/`:

- `docker-compose.override.yaml` — Caddy/TLS proxy override **plus** the backend
  image override (see `docker-compose.override.swarm.yaml` here). Falls back to
  stock `makeplane/plane-backend:v1.3.1` when `SWARM_BACKEND_*` are unset.
- `plane.env` — `deploy.sh` maintains `SWARM_BACKEND_IMAGE` / `SWARM_BACKEND_TAG`.

The GHCR backend package stays **private**. During each gated deploy the workflow
logs the server into GHCR with its own short-lived `GITHUB_TOKEN`, pulls, then logs
out — so no long-lived registry credential is stored on the box.

## Required GitHub config

Secrets: `SSH_HOST`, `SSH_USER`, `SSH_PRIVATE_KEY` (deploy key), optional
`SLACK_WEBHOOK_URL`. Environment `production` with a required reviewer (set this to
Pete/Ash's GitHub accounts to make them the approvers).

## Manual operations

```bash
# Deploy a specific tag by hand (on the server)
/opt/plane-selfhost/plane-app/deploy.sh v1.3.1-swarm.abc1234

# Roll back: just deploy the previous immutable tag
/opt/plane-selfhost/plane-app/deploy.sh <previous-tag>

# After any upstream upgrade, sanity-check the fork markers
grep -rl "GUEST-VISIBILITY FORK" apps/api/
```
