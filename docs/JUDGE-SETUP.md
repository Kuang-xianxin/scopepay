# ScopePay judge setup — v1.2.1 local build

On October 28, an authorized official Sandbox run completed OAuth, one USD 1.00 virtual order, buyer approval, capture and server verification; repetition kept the same receipt and one capture. See [evidence and limits](SANDBOX-20261028.md). The default judge configuration remains a clearly labelled simulation with no embedded credentials. Judges need their own/private authorized Sandbox configuration to repeat the official path.

ScopePay runs on Python 3.12 with a browser. The default demonstration is a clearly labelled local payment simulation. No PayPal account, model download, PostgreSQL server or frontend build is needed for that path. It is a functional workflow, but **does not establish the contest's required real Sandbox integration**.

## Install and run (Windows PowerShell)

Start with the anonymous clone and pinned checkout in the [English quick start](../README.md#judge-quick-start-windows-powershell) or [中文快速开始](../README.zh-CN.md). Use a new clone directory and explicitly select Python 3.12. From its root:

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip check
if (Test-Path .env.judge) { throw 'Keep the existing config; use a new clone directory.' }
if (Get-NetTCPConnection -State Listen | Where-Object LocalPort -eq 18231) { throw 'Port 18231 is occupied; choose an unused port. Do not stop its owner.' }
$judgeConfig = (Get-Content .env.judge.example -Raw).Replace('127.0.0.1:18216', '127.0.0.1:18231').Replace('data/judge/scopepay.db', 'data/judge-18231/scopepay.db')
$judgeConfig | Set-Content -Encoding utf8 .env.judge
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/run_local.py --config .env.judge
```

Open `http://127.0.0.1:18231`. The command stays in the foreground; Ctrl+C stops that process. If the port is occupied, choose a different unused port in this config's `APP_URL` and the scenario's `--url`; do not kill an unknown listener. `DATABASE_PATH` is relative to the repository root unless absolute. Keep each judge run's data directory. The explicit config does not merge the repository `.env` or inherited provider environment. Do not copy development credentials. The example file's original 18216 port is replaced only in this new local config.

On October 31, the public commit `8aaf4e1309f66d58b3d50373898fe8e8d72d5e59` (69 tracked files) was anonymously cloned into a new directory and installed in a new Python 3.12.7 venv with system site-packages disabled. Pinned installation and `pip check` passed. Pip reused some cached downloads; this was a fresh environment, not a cache-free download or fresh OS. Actual HTTP checks used port 18231 and an empty `data/judge-18231` database. No application code, dependency or example-config change was needed. The first one-off harness attempt stopped before startup on a PowerShell empty-listener exit code; its failure was retained and the corrected harness passed. This check did not rerun PostgreSQL, browser interaction, models or official Sandbox. The owned test listener was stopped afterwards.

## Five-minute functional check

Use another terminal in the same directory:

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/judge_scenario.py --url http://127.0.0.1:18231 --output data/judge-check-01.json
```

This explicitly synthetic, manual-input scenario uses actual local HTTP. It refuses to run if the server reports Sandbox mode. It retains three purchases:

1. Two landing pages at $120 each plus a $60 handover guide; hosting excluded, budget $350. A changed $301 confirmation is rejected. A simulated lost capture response becomes Unknown, then reconciliation produces one $300 receipt. Repeated actions return that receipt.
2. An approved purchase is revoked before capture. Capture is rejected.
3. A separate approval expires after four seconds of real elapsed time. Capture is rejected. No system clock is changed.

Open the returned URLs or refresh the purchase register. The payment mode label remains visible. Export the receipt from the UI. Reusing an output filename is refused; choose a fresh filename for another run. Do not delete previous evidence to rerun.

The retained JSON must say `official_sandbox_verified: false`, `model_called: false`, and `source_kind: manual_synthetic`. The recovered receipt must say `mode: simulation`, `payment_verified: false`, and `total_cents: 30000`. `same_receipt_on_repeat` and `export_verified` must both be true. These fields are deliberate evidence boundaries.

### Expected errors and recovery

| Situation | Expected result | Action |
|---|---|---|
| Altered USD 301 confirmation | HTTP 409, `confirmation_amount_currency_or_fingerprint_mismatch` | Confirm the locked quote's USD 300 amount. |
| Simulated lost capture response | HTTP 504, `simulation_response_lost_verify_status` | Read Unknown, then reconcile the same simulated order into one receipt. |
| Revoked approval | HTTP 409, `quote_approval_revoked` | A withdrawn approval cannot authorize capture. |
| Approval expired after four seconds | HTTP 409, `approval_expired_use_revision` | Create a revision and obtain a new approval for future work. |
| AI button with empty `OPENAI_MODEL` | HTTP 503, `model_not_configured` | Use manual entry or arrange an authorized running local model. This response makes no model request. |
| Reusing the scenario output filename | Exit 1, `Refusing to overwrite evidence` | Choose a new filename; keep the previous JSON. |
| Missing explicit config | Exit 1, `Invalid explicit configuration; no values logged.` | Check the file path; do not fall back to the developer `.env`. |
| Blank Sandbox template with offline preflight | Exit 2, `configuration_incomplete`, zero orders/captures | Private authorized setup is pending. Do not add `--oauth` just to clear this warning. |
| Non-loopback scenario URL | Exit 1, `Only a loopback HTTP origin is allowed` | Use the local APP_URL. No remote request is made. |

Dependency installation needs network/package access; a venv alone does not install dependencies. Keep Python 3.12 and the lockfile unchanged when diagnosing installation errors. The Windows commands above are the verified platform; Linux/macOS installation has not been exercised in this round.

## Optional AI path

The application calls a configured, already running, authorized local OpenAI-compatible endpoint; it does not use the coding assistant as inference. Set `OPENAI_BASE_URL` and `OPENAI_MODEL` in the explicit config. Keep the endpoint on loopback. The UI's AI suggestions start unselected with zero price. A human must inspect source quotations, inclusion, quantities, prices and the approval deadline.

For the original shared competition machine, `qwen3.5-4b` at port 11436 was initially absent on 2026-10-28. The coordinator restored the existing service at 13:46. At 13:54 this project verified one real browser-to-application-to-model request under the shared serial executor: two landing pages and a handover guide were suggested, hosting remained excluded, both suggestions were unselected and priced at zero. The coordinator separately reran the six-case set; see [model evidence](MODEL.md). These small synthetic checks are not a general accuracy estimate. This worker did not start or download a model. On the shared machine, all model calls must go through the coordinator's existing isolated-check executor. Judges on their own machine can use their own authorized local endpoint.

## Official Sandbox path — independently reproducible with authorized test credentials

The user must supply their authorized Sandbox REST app credentials, that app's seller merchant ID, and a separate buyer test account. ScopePay serves one configured seller; the supplier text is descriptive, not a payout instruction. It does not transfer funds to arbitrary vendors or operate a delegated buyer wallet.

Copy `.env.sandbox.example` to a private file outside any publication allowlist. Fill `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_MERCHANT_ID`. Use a fresh `DATABASE_PATH` and loopback `APP_URL`. Merchant IDs follow the official 13-character account-ID format. Do not put values into screenshots, public code, command arguments, logs or submission prose.

```powershell
# Offline: configuration presence and validity; zero network requests.
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/sandbox_preflight.py --config D:/private/scopepay-sandbox.env --output data/preflight-01.json
# Only after authorized personal setup: OAuth token exchange, no order or capture.
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/sandbox_preflight.py --config D:/private/scopepay-sandbox.env --oauth --output data/preflight-02.json
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/run_local.py --config D:/private/scopepay-sandbox.env
```

The example private path must be replaced with your actual file. OAuth success only proves app authentication. It does not prove merchant identity, buyer approval, checkout, capture, webhook delivery or contest acceptance. Missing configuration exits with code 2 and makes no network request. The endpoint is hardcoded to `api-m.sandbox.paypal.com`; production mode is rejected.

To repeat authorized Sandbox testing: create a new quote, approve its exact scope and amount, create the order, use the returned official Sandbox approval URL as the test buyer, return and refresh, then explicitly capture. The server validates order ID, quote ID, amount/currency, payee merchant and completed capture identity before creating a verified receipt. Return URLs never mark an order paid. The coordinator completed one such virtual transaction at 15:29 China time on October 28; no real payment was performed.

Webhooks are optional for the manual GET reconciliation path. A true incoming webhook requires a separately authorized HTTPS receiver; the current private loopback service is not such a deployment. Do not claim verified live webhook delivery from transport fixtures.

## Current recorded demonstration

The final video is 138.666016 seconds. Its synthetic quote is USD 250 within a USD 300 cap, while the CLI check above intentionally uses USD 300 within USD 350. The final segment displays the independently completed USD 1.00 Sandbox receipt; it does not perform a new capture. Model suggestions shown in the video were previously saved from actual inference. See [recorded demo guide](DEMO-STORYBOARD.md).

For optional AI on a judge-owned machine, set `OPENAI_MODEL=qwen3.5-4b` only when an authorized loopback endpoint is already serving that model; set `OPENAI_BASE_URL` to that actual endpoint. Empty `OPENAI_MODEL` keeps manual operation available. There are no bundled weights or hidden inference credentials. If the model fails, do not relabel manual output as AI.

## Access for judges

The [source repository](https://github.com/Kuang-xianxin/scopepay) and [English video](https://www.youtube.com/watch?v=j9u4mM1TA-I) are public; the Devpost draft remains unsubmitted. The October 31 local work does not publish its document corrections automatically. The build is loopback-only and is not a remotely hosted demo. Full AI/Sandbox access still needs a private handoff: the coordinator must verify testing-field visibility, assign an authorized model endpoint, arrange the existing authorized test app/seller/buyer access and specify an availability/support period. No credential delivery, ready full-access environment or organizer agreement is claimed. Never put merchant secrets in public source or public project text. A public local simulation and existing integration evidence do not by themselves provide judges with the full integration environment.

## Contract checks

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest -q tests/test_sandbox_contracts.py tests/test_paypal.py tests/test_capture_snapshot.py tests/test_revocation.py tests/test_workflow.py tests/test_hardening.py -p no:cacheprovider
```

Provider responses in these tests are `httpx.MockTransport` fixtures. Test databases are retained in `data/test-runs`. This command is a focused regression suite, not a load test, live Sandbox proof or AI evaluation.
