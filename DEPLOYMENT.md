# Private deployment

Deployable scope: a private loopback purchase-review workspace, with local simulated processor or an operator-configured PayPal Sandbox adapter. No production payment endpoint exists. Public multiuser hosting is not ready: authenticated identities, tenancy and trusted remote approval are outside this release. Reviewer names are local review attestations.

## Clean installation

Use Python 3.12. There is no Node build, frontend CDN, browser extension, model download, or SQLite-only restriction. Install pinned dependencies into a new environment, not over an unrelated one.

```powershell
python -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
Copy-Item .env.product.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

The Windows launcher binds `127.0.0.1:8215`, strips inherited provider credentials from its child environment, retains logs, refuses an occupied port, and records actual worker PID/path/start time in `runtime.json`. Stop with `scripts/stop.ps1`; it verifies process identity and deletes no files. Direct portable startup: `python scripts/safe_run.py python -m uvicorn main:app --host 127.0.0.1 --port 8215 --workers 1`. App middleware also rejects non-loopback clients. Do not add a public tunnel/proxy to bypass this boundary.

The delivery check used a genuinely new `--without-pip` venv and 25 hash-verified official wheels, extracted without running uninstall or cleanup. All wheel downloads were retained. The clean environment ran product/payment tests successfully. Local package HTTP startup validation is recorded separately; a Docker file or cloud deployment is not claimed as tested.

## Configure persistence

Default SQLite persists under `data/`. For PostgreSQL set `SCOPEPAY_PG_CONFIG` to a private config file. Only the project `.env` is used by default; unrelated inherited `OPENAI_API_KEY` and provider endpoints are ignored. Settings repr excludes secrets and database DSNs. See DATABASE.md for tested migration, backup and restore commands. Multiple workers can serialize payment intent through PostgreSQL; the UI has one shared private workspace, not multiple organizations.

Readiness: `/api/health` is liveness/configuration; `/api/ready` verifies the database and schema. It reports Sandbox configuration and model configuration separately and never treats configuration as a successful external integration. `/api/metrics` exposes low-cardinality counters for the current worker and pool; it exports no source text, keys, usernames or request IDs.

## Sandbox and AI

Set `PAYMENT_MODE=sandbox` plus authorized `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and optional webhook ID in the private file. All PayPal URLs remain fixed to Sandbox. The application cannot sign up for an account, charge production funds, or supply the user's missing account. A real OAuth → order → buyer approval → capture → signed callback verification is still required before claiming live integration.

AI is optional. Manual inputs complete the product workflow without a model. Set an authorized shared loopback endpoint, exact model ID, and context/output limits. `scripts/evaluate_model.py` provides six bilingual source-grounded extraction cases; run serially only through the coordinator's shared isolated-check wrapper. Two batches and a browser call are recorded in docs/MODEL.md. The historical failed extraction is not a new success. The server never grants the model pricing, approval or payment tools.

## Release contents

The private release process uses an explicit allowlist. The machine-specific benchmark and older private-release builder are excluded from the public candidate; neither is needed to install, run or test the local judge workflow. It excludes `.env`, all databases, logs, runtime state, original private input, evidence/downloads, private registration files, and previous delivery receipts. The output is a local reviewable archive, not a public upload. Original files remain on disk. Preserve the private working database separately when installing a new package.

## Operational limits

Current v1.1 hardening adds schema v4, durable finite reconciliation, a synchronous-work limit of8 per process, bounded upstream bodies and GET-only Tenacity retry. These apply in both the source tree and the new release package. Real HTTP benchmark/memory boundaries and fault reproduction are in docs/HARDENING.md. The unknown result workflow has no background recapture worker; explicit checks resume persisted leases after a restart.

- This version has no refund/dispute/fulfillment subsystem, tax engine, recurring budget ledger, or arbitrary supplier payout capability.
- The fixed-price scope is the entire payment intent; quantity and rate changes require a new quote/review.
- There is no cache in the authorization path; cache invalidation/stampede is deliberately inapplicable here.
- Retained logs, backups and history need a human-approved retention policy. No automatic deletion is enabled.
- Concurrency checks are local bounded measurements, not a production traffic guarantee. See docs/RELIABILITY.md.

Connection budget:4 pooled connections/worker including business locks; one worker by default, maximum two workers within this project’s8-connection allocation. Shared model inference remains one active call/worker; coordinate its shared endpoint before parallel deployments. Stop every old-version worker before switching SQLite lock-file strategies.
