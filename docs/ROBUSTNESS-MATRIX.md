# Reliability matrix / v1.1

Historical evidence: retained private October 23–24 hardening records. All data are synthetic or retained private records. Provider failures use explicit mocks; no official payment is implied. Commands below must use `scripts/safe_run.py`; load, fault batches and model runs also use the coordinator's `run-isolated-check.py` global lock.

| # | Trigger and mechanism | User behavior / code | Reproduction and evidence | Boundary |
|---|---|---|---|---|
| 1 | Bursts:24 full-ASGI requests and8 actual sync functions/worker; fixed503/Retry-After;5s send timeout including503/504 | Busy, preserved input; admission.py,execution.py | verify_runtime.py --coordinated;10k rows,1/10/30,10s each; runtime-verification.json; test_response_deadlines.py preserves2before-fix failures | Loopback realHTTP, not internet capacity;30 concurrency had1181 refusals |
| 2 | Competing draft versions; per-key PG locks and optimistic version |409/reload, no overwrite; workspace.save/submit | test_product.py; PG regression | Shared private operator scope, no tenant identity |
| 3 | Repeated approval/order/capture; fixed snapshot, stable keys, unique receipts | Same result or409 mismatched parameters; payments.binding/check_binding | test_hardening.py; two_process_capture in runtime evidence | No global third-party exactly-once guarantee |
| 4 | Cancelling HTTP while sync function runs | Work slot remains occupied; new work503; execution.py | test_sync_capacity_counts_real_work_after_caller_disappears; admission slow send/receive tests | No async job queue in product; there is no fictitious cancellation of a payment already dispatched |
| 5 | Process exits immediately after intent/processor commit | Unknown remains or recovers one receipt; payments.dispatch_intent/refresh | Real exit73 child at each boundary; runtime crash_recovery | Before-side-effect crash remains conservative unknown |
| 6 | Pool4 exhausted, broken connection, row lock2s, deadlock |503 with bounded wait; storage.tx/release/operation | runtime pool/row_lock/closed_connection; test_resource_faults PostgreSQL deadlock | Shared server itself not restarted |
| 7 | Slow pg_sleep,10k-row list/search |5s SQL cancellation; page before detail joins; workspace.register | runtime plans includeANALYZE/BUFFERS/loops, slow_sql5.015s | Count and contains-search scan metadata; no million-row/cold-cache claim |
| 8 | Oversized inbound/upstream/history |64KiB inbound;128KiB upstream/16KiB OAuth;200 activity rows; export >5000 refused | app.local_boundary,remote.py,workspace.snapshot; oversized tests | Backup remains a bounded-local-scale logical snapshot, not streaming TB archive |
| 9 | Repeated actual HTTP list/snapshot/export | Work slots0, waiters0, pool idle | server-memory-corrected.json:30 warmup,500 mixed requests,6samples,actualserver PID | Earlier launcher RSS explicitly superseded; no proof of zero leaks |
| 10 | Concurrent OAuth cache miss / auth failure | One token refresh, early expiry, cooldown3s,wait<=2s | PayPal._oauth; test_auth_cache_singleflight_and_failure_cooldown | One-entry cache; business facts uncached; multi-key avalanche not applicable |
| 11 | Timeout/disconnect/5xx/malformed upstream | Typed error, byte/deadline bounds; remote.py,PayPal,Extractor | protocol tests + fresh model-evaluation.json | Official Sandbox not called |
| 12 | Retry storm / repeated side effect | Tenacity onlyGET2 attempts; capture never replayed; create3 explicit attempts same key | test_get_retries_are_bounded_capture_is_not_replayed | No automatic retry of unsafe POST |
| 13 | Unknown or partially observed settlement | Persistent check lease/token, backoff,5-attempt/manual state; one receipt | test_reconciliation_attempts_and_backoff_survive_reopen; realcrash cases | No refund/compensation implemented; manual investigation can remain required |
| 14 | Injection/path/bad types/source attacks | Pydantic strict contracts,bound SQL,HTML escaping,fixedSandbox URLs,model has no tools | tests product/workflow/paypal/model; UI source unchanged | No file/ZIP/CSV importer in product; package extraction separately validates paths |
| 15 | Foreign host/origin, stale session, secret repr |403, private loopback only; app.local_boundary,Settings repr=False,safe_run | test_product.py + request security tests | No remote auth/tenant separation; public hosting not ready |
| 16 | Diskfull/migration/backup corruption | SQLite real page quota failure507 rollback; additive v4; new-schema restore equality | test_resource_faults.py; runtime restore; live-preservation.json | Physical PG disk-failure not injected into shared cluster; no source deletion |
| 17 | High cardinality / unbounded history | Fixed metric names; UI/audit paging, no repeated same-state audit event | app.metrics,payments._commit_summary; audit pagination test | Persistent history/log disk growth requires approved retention; no auto-delete |
| 18 | Double-click, disconnect, refresh, late response, language/narrow/keyboard | busy guards,route generation inclnestedcatch,110sfetchdeadline | actual Egolite rounds03–06; browser-race.json, screenshots | One synthetic503/delay fixture is labelled separately from actual lost-response simulation |
| 19 | Changed source/quote/receipt or approval binding |409; never export known mismatched receipt | Store.quote/analysis,Workspace.snapshot,Payments.check_binding; integrity tests | Local hashes are integrity checks, not external tamper-proof signatures |
| 20 | Clean install/start/restart/health/shutdown |26 pinnedhashchecked wheels,newvenv,additive migrations,private startup | clean-install-v4.json; clean-pg-final.xml; release-http.json | Local extracted deployment verified; public/cloud deployment not performed |

## Commands

Unit/protocol and PG: `python -m pytest -q tests/test_hardening.py tests/test_product.py tests/test_paypal.py tests/test_revocation.py tests/test_admission.py --postgres-config <private-config> --tb=short`. For deadlock/diskfull add `tests/test_resource_faults.py`; the nonmatching engine case explicitly skips.

Historical HTTP/crash/SQL/load and actual-server memory measurements used private machine-specific harnesses, which are not bundled or required for judge reproduction. Do not treat those historical numbers as fresh measurements. For the supported public walkthrough use `scripts/judge_scenario.py` and JUDGE-SETUP.md; it exercises real loopback HTTP in simulation.

Fresh real model: `python scripts/evaluate_model.py --base-url http://127.0.0.1:11436/v1 --model qwen3.5-4b --max-tokens 1536 --output <new-json>` through shared wrapper. Semantics are reviewed separately from JSON/source validity.

Clean artifact HTTP: `python scripts/deployment_smoke.py --archive <new-release-zip> --extract <new-directory> --output <new-json>`. Read stdout/stderr/result and inspect screenshot contents; tool completion alone is not acceptance.
