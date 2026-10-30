# Reliability evidence and boundaries

Historical evidence: private October 23 product-validation records, retained outside the public source. Tests retain isolated SQLite files and PostgreSQL verification schemas; no bulk deletion or external load occurred. The current package is a private local tool, not a public production service.

The machine-specific `reliability_check.py` harness and its private PostgreSQL config are not distributed in the public candidate. References below document historical evidence; they are not standalone judge commands. Use JUDGE-SETUP.md and the bundled `scripts/judge_scenario.py` for reproduction.

## Measured load

Real PostgreSQL18.6, 1000 synthetic quotes, FastAPI via in-process ASGI HTTP requests, one worker. The original run used a retained project load lock; the final run used the coordinator shared isolated-check wrapper; each stage lasted about10seconds, no model/provider traffic. These are local measurements, not internet/server capacity claims.

| Concurrency | HTTP200 | HTTP503 | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 252 | 0 | 18.96 | 25.34 | 29.14 |
| 10 | 1400 | 0 | 47.79 | 72.74 | 98.29 |
| 30 | 993 | 1440 | 40.99 | 249.27 | 320.69 |

At30concurrent requests, admission/pool limits deliberately refused excess work. The combined latency distribution includes refused responses; it is not an all-success p95. Pool returned to six available connections, zero waiting requests, and ready=true. The first RSS probe returned invalid zeros because the Windows handle signature was wrong; those values are not used. A corrected120-request post-warmup window measured RSS59,142,144→59,695,104bytes and Python retained+51,148bytes, peak451,135bytes. This window does not prove absence of memory leaks.

Four independent OS processes captured one simulated payment simultaneously: all returned the same settled order; one capture audit event and one unique receipt were recorded. SQL `pg_sleep(6)` was cancelled at the configured five-second statement limit; pool exhaustion returned503 and recovered after release. Query EXPLAIN/ANALYZE is preserved in `reliability-result.json` (1000-row actual list query,3.74ms execution in that sample).

## Failure matrix

| Trigger | Protection / user behavior | Implementation / reproduction | Actual result or boundary |
|---|---|---|---|
| 1. Request burst | 24full-lifetime API requests;503 with Retry-After | admission.py full-ASGI middleware; `scripts/reliability_check.py` | 1/10/30 measured above |
| 2. Two windows save | expected_version conflict; input retained | Workspace.save; test_budget_draft_conflict_and_submit_idempotency | Real SQLite and PG passed |
| 3. Duplicate submit/order | Stable draft ID, immutable quote, fixed request IDs; changed parameters409 | tests/test_product.py, test_paypal.py | Concurrent submit and changed scenario tested |
| 4. Model queue full | One inference slot/worker,429; explicit manual alternative | app.py analyse; test_secret_repr_and_model_backpressure | Slot release in finally; no background queue |
| 5. Crash/response loss | Durable dispatch intent; only reconcile while unknown | Payments.capture/refresh; product loss/restart test | Restart and cross-database browser recovery tested |
| 6. Pool/lock exhaustion | Four pooled connections including advisory locks/eight waiters/two-second wait; short write transactions | storage.py; reliability_check.py | Fault/recovery passed; top-level operations capped2/process |
| 7. Slow/N+1/unbounded query | Lightweight indexed projection, SQL LIMIT100, bounded offset10000 | Workspace.register; recorded EXPLAIN | Contains-search scans remain; no millions-row claim |
| 8. Large bodies/fields | 64KiB streamed request limit,12k source chars,20items; result limit | local_boundary, Pydantic models | Body/field/limit tests passed; no upload parser |
| 9. Memory retention | Context-managed HTTP/DB resources; finite counters; measured warmup/window | memory_probe.py and corrected evidence | +51KB Python retained / +0.53MiB RSS in one120-read window |
| 10. Cache failure | No cache for quotes/authorization/payment; OAuth refresh mutex | payments.py PayPal._oauth | Business cache stampede inapplicable; no Redis added |
| 11. Remote errors | Bounded HTTP timeout, strict response/citation validation; no fake success | extraction.py, payments.py; protocol/model tests | MockTransport tests; live Sandbox still blocked |
| 12. Retry storm | No auto retry of capture after unknown; create only same key within5hours | Payments.create/capture | Repeated capture/refetch preserves one result |
| 13. Partial/unknown result | Persisted processor side effect vs observed local state; explicit reconcile | simulated_captures / orders / receipts | Real browser lost-response recovery and unique download passed |
| 14. Injection/XSS/SSRF | Parameterized SQL, escaped user DOM, CSP, loopback models, fixed Sandbox URLs | existing workflow/model/PayPal tests | SQL search literal/URL negative cases tested |
| 15. Session/cross-workspace | Loopback-only client/Host/Origin; local token persists; secrets hidden | local_boundary / Settings | Not remote authentication or tenants; public hosting blocked |
| 16. Failed writes/backup | Transaction rollback; additive migration; overwrite refusal; restore-new only | db_admin/migrate/restore; migration tests | PG restore passed after retained first failure; physical disk-full injection not performed |
| 17. Unbounded logs/history | Low-cardinality finite metrics, no source/config in errors; retained records | /api/metrics; safe_run/start.ps1 | No auto deletion; long-term retention policy remains operator work |
| 18. UI rapid/late/offline | Busy disables mutations/navigation, query generation guards, draft local persistence | workspace.js; Egolite scripts | Save/reload/language/unknown/revision and narrow flows tested; controlled offline UI separately recorded |
| 19. Corruption | Quote fingerprint and source digest checked before approval/export | storage.quote/analysis; corruption tests | Both engines reject modified bodies; not an external tamper-proof ledger |
| 20. Install/restart | Pinned wheels, new venv, source-only ZIP, liveness vs readiness, verified stop identity | deployment_smoke.py / scripts/start.ps1 | Clean environment tests passed; package HTTP outcome in final delivery record |

## Reproduction

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest -q --tb=short
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe -m pytest tests/test_product.py tests/test_paypal.py tests/test_revocation.py -q --postgres-config D:/private/paypal.json
# Historical machine-specific load harness omitted from this public candidate.
```

The reliability script's config/output paths are local acceptance defaults; change them for another machine, and coordinate the global load slot. It seeds only its own new verification schema. No production DB, financial account, real payment, public endpoint or user email is part of the test.

## Final coordinator-driven rerun

`reliability-v2.json` is the current result after pool/admission/query changes. The old combined-latency and invalid-RSS result remains historical evidence. New run:1000 synthetic quotes, ANALYZE on own verification tables, real PostgreSQL18.6, in-process ASGI requests,10seconds per stage. No controlled cold-cache claim.

| Concurrency | Status | Count | p50 ms | p95 ms | p99 ms |
|---:|---:|---:|---:|---:|---:|
|1|200|329|9.02|17.29|23.27|
|10|200|2542|16.09|36.66|52.12|
|30|200|1182|96.79|206.97|240.76|
|30|503|2939|23.46|45.35|69.62|

Four independent capture processes again recorded exactly one capture and receipt. Five temporary test workers had a theoretical20 pooled-connection ceiling plus one monitor; the observed test-database peak was8 including the monitor. Steady deployment is one worker, maximum two by project budget. Pool returned4 available/0 waiting; readiness recovered. SQL cancellation occurred at5.01s. Full-ASGI slow-upload/slow-send/cancellation and commit/rollback/cleanup fault tests passed on both DB configurations.

The default unfiltered list now pages50 projection rows before joining quote/order metadata. EXPLAIN after ANALYZE: purchase_index index scan50 rows; planner chose one sequential scan of1000 quote rows plus hash joins; execution0.542ms in this sample. Counts and contains/status filters still inspect metadata. This does not claim all scans were removed or whole-request latency equals query time. Previous plan remains in reliability-result.json.

After warmup,120 business-list reads measured process RSS67,469,312→67,489,792bytes and Python retained+52,854bytes, peak452,331. These are an observed window, not a proof of no leak. Application history/backups remain retained and unbounded on disk until an operator approves a retention policy; JSON backup/export is appropriate to this bounded private workspace, not an unlimited archive streaming service.
