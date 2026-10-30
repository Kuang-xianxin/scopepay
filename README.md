# ScopePay

**Private publication review, October 30:** the current English video is 138.666016 seconds. It shows a USD 250 simulation and a separate existing USD 1.00 official Sandbox receipt. The command-line judge scenario intentionally uses USD 300. Source and video URLs are pending publication. See the recorded demo guide and judge setup; no new transaction is needed to review these artifacts.

**v1.2.1 integration update (2026-10-28):** official Sandbox OAuth → order → buyer approval → USD 1.00 virtual capture → server-verified receipt completed. Repeat capture and refresh kept one receipt and one dispatch. The provider's optional `amount.breakdown` exposed a whole-object equality bug, now fixed while retaining exact monetary and recipient checks; 30 related regressions pass. See [current integration evidence](docs/SANDBOX-20261028.md). Earlier v1.2 statements below describe the pre-integration build.

Start with [judge setup](docs/JUDGE-SETUP.md), [current factual evidence](docs/SCORING-AND-EVIDENCE.md), [English submission draft](docs/SUBMISSION-20261028.md), [138.666-second recorded demo guide](docs/DEMO-STORYBOARD.md) and [publication preview](docs/SOURCE-PUBLICATION-PREVIEW.md). No public submission has been made.

[简体中文](README.zh-CN.md) · [Product scope](PRODUCT.md) · [Deployment](DEPLOYMENT.md) · [Database](DATABASE.md) · [Reliability](docs/RELIABILITY.md)

ScopePay is a private purchase-review workspace. Save a supplier quote, define the included work and budget, approve a fixed amount until a deadline, then follow one payment intent through approval, capture, uncertain-result reconciliation and a unique receipt. Changing scope requires a new revision and approval.

The home screen is a searchable purchase register. Drafts survive refresh, concurrent edits are version-checked, over-budget quotes cannot be submitted, and unknown capture results offer reconciliation instead of another charge. Chinese and English interfaces preserve original source and user-entered text.

v1.1 adds approval-bound payment intents, durable finite reconciliation, network work outside database locks, bounded synchronous workers, safe GET retry and stale-browser-response protection. [Architecture and failure recovery](docs/HARDENING.md) and the [20-case reliability matrix](docs/ROBUSTNESS-MATRIX.md) distinguish implemented mechanisms, actual evidence and remaining limits.

## Run

Python3.12, FastAPI/Pydantic, PostgreSQL via Psycopg3, optional local SQLite, and native browser ES modules. No frontend CDN or Node build.

```powershell
python -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
Copy-Item .env.product.example .env
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start.ps1
```

Open the loopback address printed by the launcher (port8215). The app refuses remote clients. Stop with `scripts/stop.ps1`. New installs default to the local simulated processor; the current private development installation uses real PostgreSQL. Use DATABASE.md to migrate existing data without deleting the original SQLite file.

## Complete a purchase

1. Choose New purchase or an explicitly synthetic sample. Enter a title/supplier and the original request. Add lines manually, split source lines, or ask a configured local model for suggestions. Suggestions start unselected.
2. Enter ordinary currency amounts, quantities, exclusions, budget and approval deadline. Save a partial draft or submit a completed quote. Server amounts are integer cents.
3. Review the fixed scope/total. Record a local reviewer name, acknowledge the amount, and approve or return for changes. Before capture, approval can be revoked or expire.
4. Create the payment order. With the simulated processor, choose normal completion, lost capture response, or rejection and explicitly simulate buyer approval. With Sandbox, the configured merchant account and real Sandbox buyer approval are required.
5. Capture the approved amount. If the response is lost, reload/restart safely and reconcile the same order. Never create a replacement while the result is unknown.
6. Read one receipt and its chronological history, download the record, or print the receipt. Repeated capture/reconciliation keeps the same receipt.

## Verified boundaries

The earlier 1.1 delivery records real PostgreSQL storage/migration, two-engine regressions, cross-process capture, backup/restore and a clean pinned-dependency installation. Those are historical results, not fresh 1.2 measurements. This sprint verifies the affected contracts, isolated local HTTP workflow and extracted release; see the current factual evidence document. Tests distinguish provider mocks from actual PostgreSQL and local simulation.

One real PayPal Sandbox end-to-end run is verified with authorized test accounts: USD 1.00 virtual funds and one matched completed capture. It used manual scope entry; local AI extraction has separate evidence. The adapter is Sandbox-only; there is no production payment endpoint. This is not an arbitrary supplier payout or delegated buyer wallet. Local reviewer names are attestations, not authenticated third-party signatures. Public multiuser deployment, refunds/disputes and tax calculation are outside this release.

AI is optional and never has payment authority. The historical0.5B semantic failure is retained. New actual `qwen3.5-4b` batches and a browser call completed under the shared model lock. After fixing a dropped quantity, six synthetic bilingual cases passed source/quantity checks and in-thread semantic review; this is not a population accuracy claim. See [live model evidence](docs/MODEL.md).

## Checks

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip check
```

PostgreSQL tests accept `--postgres-config <private-json>` and retain a separate schema per test in `test_database`. `/api/health` reports liveness/configuration; `/api/ready` checks database readiness. `/api/metrics` contains bounded counters, not source data or keys. See [engineering learning notes](docs/LEARNING.md) for data flow and design tradeoffs.

The local release builder uses a source-only allowlist. Private inputs, databases, credentials, logs, evidence, registration files and historical failure artifacts are never put in the release archive. No public repository push, cloud deployment, financial signup, real transaction, external message or final contest submission was performed.
