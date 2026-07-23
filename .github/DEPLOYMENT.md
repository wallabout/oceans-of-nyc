# CI/CD & Automated Deployment

This repo deploys automatically on merge to `main`. This doc explains the
pipeline and the one-time setup required to turn it on.

## Overview

| Workflow | Trigger | What it does |
|---|---|---|
| [`ci.yml`](workflows/ci.yml) | Every PR + push to `main` | Lint (ruff), format check, type-check (mypy), run pytest against an **ephemeral Neon branch**, and `astro build` the web frontend |
| [`deploy.yml`](workflows/deploy.yml) | After **CI succeeds** on `main` | Apply pending DB migrations, then `modal deploy modal_app.py` |

`deploy.yml` uses a `workflow_run` trigger, so a deploy only ever runs for a
commit whose CI (lint + tests + web build) went green on `main`.

### The three platforms

- **Modal** — hosts the entire Python backend (`modal_app.py`: submission
  webhooks + scheduled crons). CI does not touch it; `deploy.yml` runs
  `modal deploy` on merge.
- **Neon** — Postgres. CI creates a throwaway branch per run for tests;
  `deploy.yml` applies migrations to the production database.
- **Cloudflare Pages** — the Astro site in `web/`. **Already automated** via
  Pages' native git integration + the deploy hook that `modal_app.py` fires
  when data regenerates. CI only *build-checks* `web/`; there is no
  Cloudflare deploy step here by design. (To move that deploy into CI later,
  add a `wrangler pages deploy web/dist` job with a `CLOUDFLARE_API_TOKEN`.)

## One-time setup

### 1. GitHub Actions secrets

Repo → Settings → Secrets and variables → Actions → **Secrets**:

| Secret | Where to get it |
|---|---|
| `MODAL_TOKEN_ID` | Modal dashboard → Settings → API Tokens → *New token* (or `modal token new`) |
| `MODAL_TOKEN_SECRET` | Same token as above |
| `NEON_API_KEY` | Neon console → Account settings → API keys |
| `DATABASE_URL` | Neon production connection string (used only by the migration step in `deploy.yml`) |

The Modal-side secrets (`bluesky-credentials`, `neon-db`, `twilio-credentials`,
`cloudflare-r2`, `resend-email`, `cloudflare-pages-deploy`) already live in
Modal — the deploy just needs the token above to authenticate.

### 2. GitHub Actions variables

Same page → **Variables** (not secrets — these aren't sensitive):

| Variable | Value |
|---|---|
| `NEON_PROJECT_ID` | Neon console → your project → Settings → *Project ID* |
| `NEON_DB_ROLE` | The Postgres role tests connect as, e.g. `neondb_owner` |

> **Verify the Neon action outputs.** `ci.yml` reads
> `steps.neon.outputs.db_url` from `neondatabase/create-branch-action@v5`. If
> you bump the action version, confirm the output name (`db_url` vs
> `db_url_with_pooler`) still matches.

### 3. Baseline the production database (do this once, before the first deploy)

Production already has all current migrations, and several aren't idempotent, so
the migration runner must be told they're already applied — otherwise the first
deploy would try to re-run them and fail:

```bash
DATABASE_URL="<prod-neon-url>" uv run python scripts/apply_migrations.py --baseline
```

This creates the `schema_migrations` table and records the 7 existing files as
applied without executing them. Every deploy afterwards applies only *new*
migration files. See [`scripts/apply_migrations.py`](../scripts/apply_migrations.py).

### 4. (Recommended) Branch protection

Repo → Settings → Branches → protect `main`:
- Require the **Lint & type-check**, **Tests**, and **Web build** checks to pass
  before merging.
- Require a PR before merging.

### 5. (Optional) A `production` environment

`deploy.yml` targets an `environment: production`. Create it under
Settings → Environments to add required reviewers or restrict which branches can
deploy. It works without one, but the environment lets you gate prod deploys.

## Adding a new migration

1. Add a `.sql` file to `database/migrations/` with a sortable prefix so it
   orders after existing ones, e.g. `20260721_1200_add_foo.sql`.
2. Write it idempotently where practical (`IF NOT EXISTS`, `CREATE OR REPLACE`).
3. Merge — `deploy.yml` applies it to prod automatically before the Modal deploy.
