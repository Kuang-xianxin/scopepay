# Database operations

Current private installation uses PostgreSQL 18.6 on the coordinator's isolated loopback cluster, database `scopepay`. The original `data/scopepay.db` is retained, together with the original and migrated backups in the delivery record. Credentials live outside this repository; `.env` stores a private config path, never a checked-in DSN.

Psycopg 3.2.12 and psycopg-pool 3.2.7 drive the real read/write path. PostgreSQL is not a README-only option. SQLite remains an explicitly supported single-machine fallback for one private operator workspace; both engines use the same domain transaction code and are tested independently.

## Schema v4 and current recovery boundary

The2026-10-24 hardening adds order approval snapshots and persistent reconciliation attempts/leases. Remote calls now run outside advisory locks as well as outside database transactions. Only short reservations and result commits hold per-quote locks. There is no automatic capture replay; at most5 explicit recovery checks with backoff precede operator investigation. Reconfirmation with a different reviewer/note is rejected. See docs/HARDENING.md for current limits and actual two-process/crash tests; the following v2/v3 notes also describe retained legacy data.

`reconciliations` is included in the backup/restore allowlist. UI activity uses200-row pages and export caps5000 events explicitly. PostgreSQL10,000-row plans and v4 restore equality were measured in a fresh verification schema. Historical1000-row measurements below remain historical evidence.

## Records and invariants

- `drafts`: optimistic integer version, immutable once linked to a quote. An update based on an old version returns 409. Repeated submit returns the original quote.
- `quotes`: immutable JSON snapshot with fingerprint, exact integer cents, budget and UTC expiry; review/revoke/decline metadata are separate additive columns.
- `orders`: unique quote, unique remote identity, persisted create/capture request IDs and dispatch intent committed before the network call.
- `receipts`: unique quote AND unique order. A receipt is created transactionally with a settled local state. Repeated refresh/capture does not rewrite it.
- `simulated_captures`: a durable simulated processor result distinct from the application's last observation. It makes the lost-response/restart/reconcile path testable without pretending to contact PayPal.
- `audit`: append-only application activity. This is not a tamper-proof external ledger.
- `purchase_index`: bounded list projection. Queries return at most 100 records, use SQL pagination and indexed joins; source documents are not loaded for list rendering. Contains search still scans lightweight title/supplier metadata; it is not a full-text search service for millions of rows.

Schema versions 2 and 3 are additive and transactional. PostgreSQL migration takes an advisory transaction lock. SQLite migration takes BEGIN IMMEDIATE. Failed migrations roll back columns and old-order marking together. No old database/table is dropped. Legacy remote orders lacking dispatch evidence remain conservative `legacy-unknown`. Legacy settled quotes receive one backfilled receipt, marked `legacy_backfill`; its timestamp is the historical available timestamp, not an invented precise capture time.

## Concurrency and failures

Every payment operation obtains a per-quote cross-process lock. PostgreSQL session advisory locks share the same pool as short data transactions, with at most4 connections and8 waiters per worker. Two top-level operations per worker are admitted; pool wait is2seconds, SQL statement deadline5seconds, SQL lock wait2seconds and advisory retry deadline35seconds. Network calls do not hold a write transaction. Deployment defaults to one worker (4connections); at most two workers fit this project's8-connection budget. Coordinate a larger budget before adding workers. Startup migrations use one transient connection per starting worker, then close it before opening the pool.

SQLite uses at most256 hashed OS lock stripes per database; collisions serialize unrelated keys safely. Old per-key lock files are retained. Stop all old-version workers before upgrading the locking strategy. The OS releases locks on process exit. FULL synchronous transactions have a ten-second busy timeout. There is no automatic file deletion.

Full-ASGI admission covers request-body reads through the final response-body send, including cancellation;24 API requests per worker,15seconds per receive and120seconds total deadline.503/429/Retry-After report backpressure; expired response streams abort instead of fabricating a successful payload. The synchronous model/payment call has its own finite timeout and retained capacity slot until completion. Rollback/unlock/return cleanup preserves the business exception and closes failed connections; a commit disconnect reports an unknown result requiring refresh. A failed/closed pool is not claimed to self-repair arbitrarily; readiness fails and an operator can restart.

The small SQL dialect adapter only accepts application-owned fixed SQL templates and bound values. It is not a general SQL compiler and must not receive user-supplied SQL or arbitrary quoted-placeholder templates. No SQL editor/imported query feature exists. No cache holds authorization or payment truth.

Read transactions use PostgreSQL REPEATABLE READ / READ ONLY or an SQLite read transaction. Network calls occur outside database write transactions. The capture intent is never cleared by an inconclusive GET. Reconciliation can record a completed payment after an approval was revoked; it cannot restore the approval. Revocation is not a refund or remote cancellation.

These choices use the official [Psycopg pool API](https://www.psycopg.org/psycopg3/docs/api/pool.html), [PostgreSQL session/statement settings](https://www.postgresql.org/docs/18/runtime-config-client.html), and [advisory lock documentation](https://www.postgresql.org/docs/18/explicit-locking.html). Documentation was read through web search on 2026-10-23; actual PostgreSQL18.6 compatibility was separately tested locally.

## Backup and restore

Run all commands through `scripts/safe_run.py`. The tools refuse to overwrite backups or restore destinations.

```powershell
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/db_admin.py backup --target D:/backups/scopepay-new.json
# SQLite: target should be .db; implementation uses sqlite backup API and integrity_check.
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/db_admin.py restore --source D:/backups/scopepay.db --target D:/restored/scopepay-new.db
# PostgreSQL restore intentionally targets a NEW schema in test_database from private config.
.venv/Scripts/python.exe scripts/safe_run.py .venv/Scripts/python.exe scripts/restore_postgres.py --config D:/private/paypal.json --source D:/backups/scopepay-new.json --schema restore_check_01 --output D:/backups/restore-check.json
```

Logical PostgreSQL backups contain one consistent transaction's tables, including original inputs and review records; keep them private. JSON table keys are sorted, so restore explicitly follows foreign-key dependency order. A first restore failed because of ordering; its transaction rolled back and its empty schema was retained. The corrected restore passed full row equality. A corrupt/incompatible backup fails without replacing the live workspace.

Migration: stop only ScopePay, run `scripts/migrate_postgres.py --config <private-json> --source <existing-db> --record <new-empty-record-dir>`, then restart. Destination must be empty. Import checks all rows inside one transaction, retains SQLite and a verified copy, backs up `.env` privately, and switches configuration only after commit. To roll back the application, stop it and restore the previous private `.env`; do not automatically overwrite newer PostgreSQL work. Reconcile any new work first.

Keep backup schedules/retention under operator control. The application never deletes old user records automatically. Disk usage and backup age need an operational retention policy before a long-running hosted service.
