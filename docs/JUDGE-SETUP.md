# ScopePay judge setup — v1.2.1 local build

On October 28, an authorized official Sandbox run completed OAuth, one USD 1.00 virtual order, buyer approval, capture and server verification; repetition kept the same receipt and one capture. See [evidence and limits](SANDBOX-20261028.md). The default judge configuration remains a clearly labelled simulation with no embedded credentials. Judges need their own/private authorized Sandbox configuration to repeat the official path.

ScopePay runs on Python 3.12 with a browser. The default demonstration is a clearly labelled local payment simulation. No PayPal account, model download, PostgreSQL server or frontend build is needed for that path. It is a functional workflow, but **does not establish the contest's required real Sandbox integration**.

## Install and run (Windows PowerShell)

From the extracted repository root, in a new directory:

```powershell
python -m venv .venv
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pip install --no-clean -r requirements-lock.txt
Copy-Item .env.judge.example .env.judge
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/run_local.py --config .env.judge
```

Open `http://127.0.0.1:18216`. The command stays in the foreground; Ctrl+C stops that process. If the port is occupied, inspect its owner or choose a different unused port in this config's `APP_URL`; do not kill an unknown listener. `DATABASE_PATH` is relative to the repository root unless absolute. Keep each judge run's data directory. The explicit config does not merge the repository `.env` or inherited provider environment. Do not copy development credentials.

The release was extracted and exercised using the installed project Python environment; this sprint did not repeat the prior clean dependency installation. Dependency pins are in `requirements-lock.txt`. Previous 1.1 clean installation and PostgreSQL results remain historical evidence, not fresh 1.2 measurements.

## Five-minute functional check

Use another terminal in the same directory:

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/judge_scenario.py --url http://127.0.0.1:18216 --output data/judge-check-01.json
```

This explicitly synthetic, manual-input scenario uses actual local HTTP. It refuses to run if the server reports Sandbox mode. It retains three purchases:

1. Two landing pages at $120 each plus a $60 handover guide; hosting excluded, budget $350. A changed $301 confirmation is rejected. A simulated lost capture response becomes Unknown, then reconciliation produces one $300 receipt. Repeated actions return that receipt.
2. An approved purchase is revoked before capture. Capture is rejected.
3. A separate approval expires after four seconds of real elapsed time. Capture is rejected. No system clock is changed.

Open the returned URLs or refresh the purchase register. The payment mode label remains visible. Export the receipt from the UI. Reusing an output filename is refused; choose a fresh filename for another run. Do not delete previous evidence to rerun.

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

The release preview is private; no public repository or video URL exists from this sprint. Before submission, the entrant must approve source/video publication and arrange required test access for judges via an appropriate private submission mechanism. Never commit merchant secrets to satisfy an access checklist. The currently verified build is loopback-only, so it must not be advertised as a remote hosted demo. A local functional build is permitted by the rules, but credentials/model access needed to test the full integration still require a private handoff. The authenticated form has not been inspected this round. If it cannot provide suitably private access, the entrant must resolve that with the organizers. No external contact has been made.

## Contract checks

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest -q tests/test_sandbox_contracts.py tests/test_paypal.py tests/test_capture_snapshot.py tests/test_revocation.py tests/test_workflow.py tests/test_hardening.py -p no:cacheprovider
```

Provider responses in these tests are `httpx.MockTransport` fixtures. Test databases are retained in `data/test-runs`. This command is a focused regression suite, not a load test, live Sandbox proof or AI evaluation.
