# ScopePay v1.1 reliability design

Delivery scope is a private loopback purchase workspace and simulated processor. Official PayPal Sandbox is still unconnected. A local reviewed quote is not a delegated buyer wallet, arbitrary supplier payout, authenticated external signature or production payment service.

## Main path and concurrency

FastAPI/Pydantic validates a draft → PostgreSQL stores an immutable quote → an approval binds its fingerprint, amount, currency, reviewer and deadline → an order stores that approval snapshot and stable create/capture keys → a short cross-process critical section commits a capture intent and durable reconciliation row → external work occurs without a database transaction or advisory lock → a second short critical section commits the observed result and one receipt.

The quote key is the payment idempotency scope. Reusing it with another simulation scenario or another approval snapshot returns409. Reconfirmation with changed reviewer/note returns409. Unique quote/order constraints on receipts are the final database guard, independent of the browser.

PostgreSQL uses Psycopg3 and its bounded pool directly. Session advisory locks use that same four-connection pool; at most two top-level domain operations per process hold locks. Two application workers use at most8 pooled connections in this project's allocated budget. Startup migration connections are short lived and closed before opening pools. There is no second ORM pool. This keeps existing transactions and SQL visible and testable; SQL accepts only application-owned fixed templates and bound parameters. Introducing another mapping framework would not improve these specific invariants.

## Durable recovery, not automatic capture retry

Schema v4 adds `reconciliations` plus order snapshot, create attempt/lease and reconciliation lease fields. The migration is additive and transactional; original SQLite and PostgreSQL records remain intact. `db_admin.TABLES` and restore tooling include recovery state.

`pending → checking → resolved`, or `checking → pending/manual`. Explicit checks claim a60-second persisted lease; process death cannot retain it forever. A new claim replaces the token; a late response with an old token cannot commit. Failed/inconclusive checks back off2/4/8/16/32seconds and stop after5 attempts, preserving unknown status and requesting operator investigation. The UI does not offer another capture. There is no hidden background worker and no unbounded job queue. The user-triggered check resumes the durable record after restart.

If the process dies after capture intent but before any processor fact, the outcome remains unknown. If it dies after the simulated processor commits but before receipt creation, a check recovers exactly one receipt. The first case intentionally does not infer that no payment occurred. There is no automatic refund or compensation that could introduce another financial side effect.

Sandbox order creation can explicitly retry the same stored key at most3 times within the pre-existing5-hour window. It reserves a lease before network work. Capture is dispatched at most once by ScopePay. GET observations alone use Tenacity9.1.2 with at most2 attempts and randomized exponential wait up to400ms. The adapter has a20-second attempt-group budget,3-second connect and8-second I/O timeouts; an in-flight I/O can exceed the remaining budget by its8-second timeout. No next network operation begins after the budget. Response byte limits precede JSON decoding. Official integration remains unverified; protocol tests use MockTransport.

## Resource bounds and degradation

- ASGI admission:24 active API requests, full receive-through-send lifetime,15-second receive and120-second outer deadline. Every send has a5-second timeout; rejected503 and fallback504 replies also have a5-second total reply timeout. Once headers start, a send timeout aborts without sending another header. Busy responses carry503/Retry-After.
- Synchronous endpoint capacity:8 running functions, counted until their actual thread exits. A cancelled HTTP caller does not free this capacity prematurely. There is no executor with an unbounded pending queue.
- Model work:1 call per application worker plus coordinated shared-endpoint scheduling for evaluation. Loopback-only endpoint, bounded input/output, Pydantic structure and source citation checks. Model output never has payment authority.
- SQL pool wait2seconds; row-lock wait2seconds; statement deadline5seconds; failed rollback/return/unlock preserves original errors and releases local slots. Commit disconnect is an unknown outcome, not an asserted rollback.
- PostgreSQL register query returns at most100 records; the default list pages compact rows before quote/order detail joins. Counts still scan the compact metadata projection; contains-search remains O(n).10,000-row EXPLAIN ANALYZE/BUFFERS plans include full loops and scan counts. This is not a million-row search benchmark or cold-cache measurement.
- Activity UI pages200 rows; export refuses over5000 events rather than silently dropping history. `/audit?before=<seq>&limit=200` permits bounded keyset paging. Original audit rows are retained.
- OAuth is the only cache:one token, singleflight refresh, early expiry,3-second failure cooldown and2-second waiter limit. No approval/payment truth is cached. Redis, cache sharding and TTL avalanche controls would add no value to this one-entry cache.
- Metrics have fixed keys and numeric counters; no per-quote/request/user labels. Logs and audit history are retained; operator-approved retention is required for long-running installations. No automatic deletion.
- Incoming JSON64KiB; upstream body128KiB; OAuth16KiB. Bound currencies, integer amounts, item count, source size, database query parameters, quote fingerprint, receipt identity. Cross-origin/foreign-client writes are rejected; a local anti-CSRF token does not claim to be remote authentication.

## Browser state

Every API request carries the current route generation. A response/error from an older route is ignored, including the nested error-recovery catch. Mutation recovery remains bound to its original quote ID. Task buttons are disabled during work. A110-second browser request deadline triggers a fresh read instead of assuming a write failed. Unknown payment has only reconciliation, export and navigation; terminal manual investigation has no capture/check loop.

The actual Egolite regression delayed an old recovery GET after a synthetic503 and navigated to a revoked quote. The initial attempt exposed a nested catch marking the new quote unavailable. The fix was rerun in the same Space29; the revoked quote retained its correct next action and no capture button. Actual lost-response simulation then survived reload and reconciled through keyboard Enter in390px English layout. Both languages retain original source/amount/receipt data.

## Evidence and operating limits

Historical results and all initial failures remain in the private October 23–24 hardening records, outside the public source. Unit/protocol fixtures, real PostgreSQL, real loopback HTTP, shared-model inference, and browser response fixtures are separately identified. The first HTTP benchmark sampled Windows venv launcher RSS by mistake; that memory series is explicitly superseded by an actual-server-PID measurement, while its HTTP/SQL/capture evidence remains valid. No test number implies comprehensive production readiness.

Source references read on2026-10-24: [Tenacity retry policies](https://tenacity.readthedocs.io/en/latest/), [official pinned package metadata](https://pypi.org/pypi/tenacity/9.1.2/json), [Psycopg pool behavior](https://www.psycopg.org/psycopg3/docs/advanced/pool.html), [PostgreSQL18 advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html). These are HTTP documentation reads, not evidence of live PayPal integration.

## Learning / interview

为什么先写意图再调用处理器？进程可能在网络调用前后任意位置停止。先持久化“不确定”，重启才不会把同一支付当新请求重发。代价是某些实际未发出的请求也必须保守核对。

为什么不能一直锁着数据库等网络？网络可能很慢；长锁阻止读状态和撤销，也占连接。把“预留、外部工作、结果提交”分开，靠固定请求键、持久租约和结果提交令牌保持一致性。

为什么有HTTP并发限制还要线程工作限制？HTTP取消不一定能中断同步Python函数。只计HTTP会让已经失联的后台工作无限增加；工作槽必须由函数finally释放。

为什么单回执不能只靠前端按钮禁用？另一个进程、刷新、旧请求和断网都可能重复提交。前端是交互保护，数据库唯一约束和短事务才守住业务事实。

What does a503 under load mean? Admission or pool capacity is exhausted. It is a controlled refusal, not a completed business request. Successful and rejected latency percentiles must be reported separately.

How would you prove no memory leak? A finite RSS window cannot prove it. Measure the real worker process after warmup, track handles/connections/work, preserve repeated samples, and describe the measured workload and duration.
