# Competition fit and factual evidence — judge reproduction update 2026-10-31

**October 28 integration evidence, v1.2.1:** official Sandbox OAuth, create, buyer approval, capture and server GET succeeded for one USD 1.00 virtual transaction; repeated capture/refresh retained one dispatch and the same receipt. The first GET revealed optional amount metadata that strict whole-object equality rejected; 30 affected regressions pass after the fix. AI extraction remains a separately verified path, not part of this specific manual-input order. Webhook delivery, real-provider lost capture response and final submission remain pending. Source and video are now public; see the [current judge setup](JUDGE-SETUP.md). Detailed integration boundaries: [Sandbox run](SANDBOX-20261028.md).

## Official requirements, summarized

The [official rules](https://paypalaihackathon.devpost.com/rules), retrieved as official public page text on 2026-10-30 (without an authenticated browser), specify a November 12, 2026, noon Pacific deadline: November 13, 04:00 in China. Five criteria carry equal weight: technological implementation, design, potential impact, innovation and presentation. The project must centrally integrate the free PayPal Sandbox and an AI tool of the entrant's choice. No particular Agent SDK is mandated by the retrieved requirements. Sponsor tools are optional for the main entry. A functional local build with complete setup instructions can provide judge access; public hosting is not mandatory. Submission needs a public licensed source repository, a publicly visible YouTube demonstration under three minutes and English materials or translations. Simulation alone cannot establish the required integration.

Access boundary: the earlier Egolite visit displayed a Cloudflare challenge; that failure remains recorded. The October 30 refresh obtained the official page through a public text retrieval tool. No browser space, account or challenge was used. This verifies published requirements, not personal eligibility, registration, contract acceptance or submission. Final eligibility and ownership statements remain the entrant's responsibility.

## Our scoring strategy (design judgment, not judge feedback)

| Criterion | Specific product case | Demonstration / evidence | Gap |
|---|---|---|---|
| Implementation | Payment authority is tied to reviewed immutable scope; recipient checked; ambiguous capture is reconciled | Actual USD 1.00 Sandbox completion and repeated-request receipt; contract checks and prior PG recovery evidence | Real-provider lost capture response and webhooks remain unverified. |
| Design | Save a purchase, review scope, pay or recover, export | Existing bilingual workspace; real local HTTP and Egolite screenshots | No usability study. |
| Impact | Small studios reviewing a service package and avoiding ambiguous repeat-payment decisions | Explicit $300 included work, excluded hosting, deadline, withdrawn authority | Audience and value remain hypotheses; no interviews, adoption or savings numbers. |
| Innovation | A narrow approval boundary survives changes and uncertain payment results | Snapshot binding plus expiry/revocation plus recovery shown together | No claim of being first or commercially unique. |
| Presentation | One service-purchase story with failure and recovery | Public 138.666016-second English video: saved model suggestions, USD 250 simulation, separate USD 1 Sandbox receipt | Final entrant declarations remain pending; not uninterrupted AI-to-Sandbox capture. |

## Functionality matrix

| Capability | Implemented | Current evidence type | Limit |
|---|---|---|---|
| Source-backed AI suggestions | Yes | Oct28 coordinator six-case actual model review plus this worker's real browser-to-app-to-model check after runtime restoration | Small synthetic checks, not general accuracy; both reviews performed by assistants. |
| Human selection, exact pricing, fixed quote | Yes | Current actual HTTP scenario and regression tests | Local reviewer name is not authenticated identity. |
| Revocation / expiry before dispatch | Yes | Current actual HTTP with a real four-second synthetic expiry; provider fixtures | Cannot undo a capture already dispatched; Unknown must be reconciled. |
| Unknown → one receipt | Yes | Current simulation HTTP and provider fixtures; earlier process-death evidence | No new live-provider uncertainty incident. |
| Official OAuth / Orders adapter | Yes, configurable | Actual OAuth, create, buyer approval, capture and GET; one USD 1.00 virtual completion | One acceptance run only; no production payments or live webhook delivery. |
| Merchant match | Yes, added this sprint | Wrong-merchant failure reproduced then blocked before capture | Seller must be the configured app account, not arbitrary vendor payout. |
| Low-risk readiness preflight | Yes | Offline CLI plus fixture-only OAuth contract tests | OAuth alone cannot prove merchant identity or checkout. |
| Public release / submission | Source and video public; Devpost draft | Fixed public commit anonymously cloned; new Python 3.12.7 venv, pinned install, pip check and three actual local HTTP simulation scenarios passed October 31 | No hosted application or final submission; full AI/Sandbox judge access remains to be arranged privately. |

## API evidence

The [Orders create reference](https://developer.paypal.com/api/orders/v2/orders-create) specifies the payee merchant field, account-ID format and custom ID. ScopePay uses the quote UUID as `custom_id`; that UUID resolves to a locally integrity-checked immutable fingerprint. The complete customer brief is not sent to PayPal. The [idempotency guide](https://developer.paypal.com/api/rest/reference/idempotency/) describes operation-specific request IDs and finite retention. ScopePay retains separate create/capture UUIDs and takes a stricter local recovery path: after a dispatch intent, it reads the original order rather than automatically resending capture. The [OAuth guide](https://developer.paypal.com/api/rest/authentication) describes the token exchange used by the optional preflight. These official documents were read this sprint; reading them is not an API integration success.
