# ScopePay product contract

ScopePay is a private purchase-review workspace for a small studio's owner or operations person reviewing a supplier's fixed-price services. The operator saves the original request and supplier quotation, selects priced work, sets a budget and approval deadline, records a review, and controls the resulting payment intent. It does not procure goods from arbitrary merchants or hold a buyer wallet.

## Complete task

Input: a pasted request/quotation, supplier name, purchase title, line quantities and unit prices, exclusions, budget, currency, review deadline and reviewer name. Prices are human input in ordinary currency units; the server stores integer minor units. One approval is for one fixed total, not an automatically spendable revolving budget. Taxes/fees must be entered as explicit lines when included in the supplied quotation; the app does not compute tax.

Path: create/edit and save draft → submit an immutable quote revision → review scope and budget → approve or decline → create payment order → buyer approves → capture → inspect one receipt. Before capture, revoke or let approval expire. After dispatch is uncertain, reconcile the same order; do not issue another payment. Revise cancelled/declined/expired work through a new draft and new approval. History, search and exports refer to durable records. Simulated processor and real Sandbox adapter stay visibly distinct.

Output: the reviewed scope, exact approved currency/amount and budget headroom, durable status, one unique receipt per quote/order, and chronological activity. Draft updates use version checks. Repeated submissions use a saved draft ID and return the same quote. Capture and revocation serialize across processes.

## Scope and evidence

The current implementation was seller-side quote checkout. We retain that payment rail: this workspace records an internal purchase review but the configured Sandbox account is the merchant receiving a test payment. There is no claim of arbitrary supplier payout or delegated PayPal buyer authority. This is a valuable testable scope-control tool independent of financial account access.

Prior retained technical research establishes spend-review workflows and PayPal's ambiguous timeout/idempotency semantics. It does not establish our target user's frequency, willingness to adopt, or ability to use the merchant payment flow. No interviews or customer transactions have occurred. Supplier quotes and browser examples used for acceptance are explicitly synthetic.

Deployment: private loopback workspace, authorized local operator(s), no organization identity or remote role separation. Reviewer names are local attestations, not authenticated third-party signatures. PostgreSQL is supported for concurrent processes; SQLite is supported for a bounded local workspace with OS locks, migrations and backups. Public multiuser access needs authentication and tenant isolation and is outside this release's deployable scope.

AI: optional evidence-backed draft suggestions only. It cannot set prices, approve scope, create orders or capture funds. Manual entry is fully functional. Six synthetic cases and one browser request were actually evaluated with the authorized shared qwen3.5-4b; see docs/MODEL.md for the first-round omission, fix and remaining limits. Historical semantic failures remain failures. Official Sandbox end-to-end remains blocked by the user's unavailable account; the adapter is configured without account creation or live transactions.

Acceptance: normal workflow, over-budget/invalid/stale inputs, decline/revision, expiry/revocation, unknown/reconcile, repeated/concurrent operations, one receipt, restart recovery, SQLite backup/restore + PostgreSQL migration, clean install, bilingual desktop/narrow keyboard UI. Each status is measured separately in delivery records.

2026-10-24 reliability scope: payment execution binds the stored approval; reconciliation has durable attempts/leases and a terminal investigation state. No automatic recapture. Explicit slow/uncertain recovery remains usable while other records can be read. New10,000-row local HTTP, process-crash and input/resource-fault evidence is described in docs/HARDENING.md. User/adoption assumptions remain unvalidated.
