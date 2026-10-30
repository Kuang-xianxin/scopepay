# ScopePay

**Public source and judge check, October 31:** [source](https://github.com/Kuang-xianxin/scopepay) and the [138.666-second English video](https://www.youtube.com/watch?v=j9u4mM1TA-I) are public. A new anonymous clone of commit `8aaf4e1309f66d58b3d50373898fe8e8d72d5e59` was installed in a fresh Python 3.12.7 environment and exercised with empty credentials, SQLite and three actual local HTTP simulation scenarios. Full AI/Sandbox judge access still needs a private handoff; no hosted demo or final contest submission is claimed. The video shows a USD 250 simulation and a separate existing USD 1.00 official Sandbox receipt; the CLI scenario uses USD 300.

**v1.2.1 integration update (2026-10-28):** official Sandbox OAuth → order → buyer approval → USD 1.00 virtual capture → server-verified receipt completed. Repeat capture and refresh kept one receipt and one dispatch. The provider's optional `amount.breakdown` exposed a whole-object equality bug, now fixed while retaining exact monetary and recipient checks; 30 related regressions pass. See [current integration evidence](docs/SANDBOX-20261028.md). Earlier v1.2 statements below describe the pre-integration build.

Start with [judge setup](docs/JUDGE-SETUP.md), [current factual evidence](docs/SCORING-AND-EVIDENCE.md), [English submission draft](docs/SUBMISSION-20261028.md), [138.666-second recorded demo guide](docs/DEMO-STORYBOARD.md) and [publication preview](docs/SOURCE-PUBLICATION-PREVIEW.md). No public submission has been made.

[简体中文](README.zh-CN.md) · [Product scope](PRODUCT.md) · [Deployment](DEPLOYMENT.md) · [Database](DATABASE.md) · [Reliability](docs/RELIABILITY.md)

ScopePay is a private purchase-review workspace. Save a supplier quote, define the included work and budget, approve a fixed amount until a deadline, then follow one payment intent through approval, capture, uncertain-result reconciliation and a unique receipt. Changing scope requires a new revision and approval.

The home screen is a searchable purchase register. Drafts survive refresh, concurrent edits are version-checked, over-budget quotes cannot be submitted, and unknown capture results offer reconciliation instead of another charge. Chinese and English interfaces preserve original source and user-entered text.

v1.1 adds approval-bound payment intents, durable finite reconciliation, network work outside database locks, bounded synchronous workers, safe GET retry and stale-browser-response protection. [Architecture and failure recovery](docs/HARDENING.md) and the [20-case reliability matrix](docs/ROBUSTNESS-MATRIX.md) distinguish implemented mechanisms, actual evidence and remaining limits.

## Judge quick start (Windows PowerShell)

Use Git and Python 3.12. The default judge path uses SQLite and manual input: no PayPal account, model download, PostgreSQL setup, Node build or frontend CDN. `python` may select another installed version; `py -3.12` selects the supported interpreter explicitly. If the Windows launcher is unavailable, use the full path to a Python 3.12 executable.

```powershell
git clone --no-checkout https://github.com/Kuang-xianxin/scopepay.git scopepay-judge-8aaf4e1
cd scopepay-judge-8aaf4e1
git checkout --detach 8aaf4e1309f66d58b3d50373898fe8e8d72d5e59
py -3.12 -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip check
if (Test-Path .env.judge) { throw 'Keep the existing config; use a new clone directory.' }
if (Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 18231) { throw 'Port 18231 is occupied; choose an unused port. Do not stop its owner.' }
$judgeConfig = (Get-Content .env.judge.example -Raw).Replace('127.0.0.1:18216', '127.0.0.1:18231').Replace('data/judge/scopepay.db', 'data/judge-18231/scopepay.db')
$judgeConfig | Set-Content -Encoding utf8 .env.judge
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/run_local.py --config .env.judge
```

Open `http://127.0.0.1:18231`. Keep the first terminal running; Ctrl+C stops that foreground process. In a second terminal at the same repository root, run:

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/judge_scenario.py --url http://127.0.0.1:18231 --output data/judge-check-01.json
```

Expect three synthetic purchases: recover an uncertain USD 300 result into one receipt, reject revoked approval, and reject approval after real expiry. A changed USD 301 confirmation is also rejected. `data/judge-check-01.json` retains the receipt and errors; its receipt says `mode: simulation` and `payment_verified: false`. Reusing that output filename is refused. Keep the new data and choose a new filename for another run. See [judge setup](docs/JUDGE-SETUP.md) for exact expected errors and optional access. If changing ports, update both `APP_URL` and `--url`. Existing developer services and data are separate.

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

The local release builder uses a source-only allowlist. Private inputs, databases, credentials, logs, evidence, registration files and historical failure artifacts are never put in the release archive. Source and video publication are recorded; cloud deployment and final contest submission remain separate, incomplete steps. The October 31 check made no model or PayPal provider request.
