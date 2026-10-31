# Vercel compatibility preview for the Railway FastAPI application

This branch is an **isolated preview experiment** based on the existing
`main` application. It does not alter Railway's Procfile, URLs, or deployment.
It does not port Python business logic into another language.

## What this branch changes

- Adds `index.py` exporting the **same** `app.main:app` FastAPI instance.
- Uses Python 3.12 (Vercel-supported) instead of Python 3.11.
- Adds `vercel.json` and `.vercelignore` to keep the function bundle smaller.
- On `VERCEL=1` sets `EXPORT_DIR=/tmp/manus-meta/exports` before
  importing the existing app. This only makes ephemeral report generation
  technically possible; **files are not durable or discoverable between
  different invocations**.
- Adds a GitHub Actions job running the whole repository suite under 3.12.

## Deployment steps (once Vercel is connected)

1. In Vercel import the GitHub repository, and select the
   `experiment/vercel-fastapi-preview` branch for a preview deployment.
2. Framework: FastAPI. Root Directory: repository root. Do **not** override
   the build command or output directory. Entry file: `index.py`.
3. Add needed environment variables in Vercel **Settings → Environment
   Variables** without committing their values to GitHub.
4. Set `PUBLIC_BASE_URL` to the *actual* preview URL and matching OAuth
   redirect URLs to their Vercel equivalents **for separate test OAuth
   clients**. Do not replace the Railway production callback URLs.
5. Verify `/health`, `/docs`, `/meta/query`, `/analysis/run`,
   `/tools/ga4`, report generation, and a signed webhook fixture.
6. Keep all real Meta webhook subscriptions routed to Railway during tests.
   Repointing live subscriptions before reliability checks could lose replies.

## Environment variables

Refer to `.env.example` and the existing Railway settings. Common names:
`PUBLIC_BASE_URL`, `SESSION_SECRET`, `GPT_OAUTH_CLIENT_ID`,
`GPT_OAUTH_CLIENT_SECRET`, `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, `META_APP_ID`, `META_APP_SECRET`,
`META_WEBHOOK_VERIFY_TOKEN`, `META_OAUTH_REDIRECT_URI`,
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_OAUTH_REDIRECT_URI`, `ALLOW_ORIGINS`, `ENVIRONMENT`.

**Never copy credentials into a GitHub file, chat, deployment build log,
or a public URL.** Where possible use dedicated preview/test credentials.
Production mode validates required session/OAuth/CORS settings at startup.

## Compatibility gates still to prove

- Build dependency and uncompressed bundle size (500 MB standard Python limit; Vercel Large Functions beta may allow bundles up to 5 GB on eligible Fluid Compute deployments; verify in the actual Preview build).
- Full API/MCP compatibility with Vercel runtime lifecycle, if MCP branch
  is subsequently included. The MCP feature PR is separate from this preview.
- Heavy analytics/reports under Vercel function CPU, memory, duration limits.
- Reliable asynchronous Facebook comment handling:
  `app/api/webhooks.py` currently uses `BackgroundTasks`, which cannot
  substitute for a durable worker or queue in a serverless environment.
- Download links for exported PDF/XLSX/DOCX/PPTX/HTML currently refer to local
  output files; they require durable object storage or same-request streaming.
- Persistent OAuth sessions and webhook integration under real traffic.
- Hobby is for personal/noncommercial use. Business use requires an
  appropriately licensed deployment and possibly paid services.

As of June 2026, Vercel has announced Large Functions (up to 5 GB) in public beta. New projects may be automatically enrolled; otherwise opt-in can use `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` scoped to Preview. This is not a substitute for checking actual resource usage and plan terms. See https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size .

**The existing application is not ready to replace Railway simply because a
Python 3.12 unit test suite passes.** Do not merge or switch the production
DNS/webhooks until end-to-end preview checks succeed.

## Run locally

```bash
python -m pip install -r requirements.txt pytest httpx
VERCEL=1 python -m pytest -q tests/test_vercel_entrypoint.py
VERCEL=1 python -m pytest -q
```

On Windows use your shell's environment variable syntax for `VERCEL`.

Reference: https://vercel.com/docs/frameworks/backend/fastapi
