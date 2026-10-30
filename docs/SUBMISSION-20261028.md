# ScopePay — English Devpost content draft

Updated for private review, October 31, 2026. Source and video are public; Devpost draft 1270989 remains at 3/5 and is not submitted, according to the publication handoff. Testing-field privacy and any remaining custom questions are for the coordinator to verify. This document does not provide participant identity, team role, rights declarations or final acceptance.

## Project name
ScopePay

## Elevator pitch
Turn a service brief into reviewed scope, a fixed quote and one recoverable PayPal Sandbox payment—with AI suggestions and human approval.

## Inspiration
When a small studio buys a website package, “two landing pages and a handover guide” is more useful than an unexplained payment total. Hosting may be excluded, approval may expire, and a lost checkout response leaves an awkward question: did the payment fail, or did only the response disappear? ScopePay explores that specific purchase-review problem. The target audience and value are hypotheses; no customer interviews, adoption or measured savings are claimed.

## What it does
ScopePay saves a brief and asks a configured local model to suggest deliverables with exact source quotations. Suggestions begin unselected and unpriced. A reviewer chooses included work, checks quantities, enters prices, sets a budget and deadline, and approves the fixed quote. The server computes integer cents. AI has no pricing, approval or payment tool.

The approval binds the quote fingerprint, currency and total to one payment intent. A changed amount or scope cannot reuse that approval. Revocation or expiry blocks capture before dispatch. Once a capture may have been sent, an uncertain result stays Unknown while the application checks the same order. Repeated successful actions return one stored receipt.

The configured PayPal Sandbox seller receives the virtual checkout payment. The supplier text is descriptive; ScopePay is not an arbitrary vendor payout system or an autonomous buyer wallet. Local reviewer names are attestations, not authenticated third-party signatures.

## How it was built
Python 3.12, FastAPI and Pydantic handle typed requests; native JavaScript modules provide an English/Chinese browser workspace without a frontend build or CDN. SQLite supports a standalone judge build. PostgreSQL with Psycopg supports the separately verified private shared-storage deployment.

PayPal OAuth and Orders v2 create/get/capture are central to the payment path. The server verifies order identity, seller merchant, quote ID, currency, amount and completed capture identity before accepting a receipt. Durable operation IDs, short database transactions and reconciliation leases preserve recovery across retries. Tenacity retries safe GET observations; ambiguous captures are not automatically replayed. Qwen3.5-4B runs locally through an OpenAI-compatible interface for optional source-grounded suggestions.

## Challenges
The real Sandbox returned an optional amount.breakdown field that strict whole-object comparison rejected. The fix compares authoritative monetary fields while still enforcing recipient and quote identity. The original remote order ID had already been saved, so recovery reused that order. Thirty related contract tests passed after the fix. The actual Sandbox acceptance is separate evidence from those mocked provider responses.

A historical smaller-model semantic failure and a later dropped-quantity case are retained. Structured JSON and exact source quotation alone do not prove correct interpretation. Human review remains part of the product.

## Accomplishments
One authorized official Sandbox run on October 28 completed OAuth, a USD 1.00 virtual order, buyer approval, capture and independent server GET. The returned status was COMPLETED, with one capture, one application capture dispatch and the same receipt after repeated capture and refresh. The scope for that order was entered manually. It was not a production payment.

Separately, actual local Qwen3.5-4B extraction was checked on six synthetic bilingual cases, and one application/browser request saved and reread its suggestions. Semantic review was performed by assistants; this is not a population accuracy estimate or an independent human study.

The local HTTP scenario covers altered-amount rejection, withdrawn and expired approval, simulated lost-response recovery, repeated receipt identity and export consistency. Its USD 300 scenario is distinct from the final video's USD 250 simulation and the official USD 1.00 Sandbox run. On October 31 the fixed 69-file public commit was anonymously cloned, installed in a new Python 3.12.7 venv and exercised with new SQLite data on port 18231. Pinned installation, pip check and all three scenarios passed; some dependency downloads came from pip cache. The documentation candidate leaves executable/configuration/dependency/test/static bytes unchanged and is still local.

## What was learned
A matching total does not establish the right recipient. A timeout does not establish that a side effect failed. A source quotation does not establish that AI understood it. These facts need separate checks. The design deliberately keeps human authority and deterministic payment control outside the model.

## What's next
Validate the purchase-review hypothesis with real target users, arrange private full AI/Sandbox judge access, and review ownership and final submission. Authenticated multiuser hosting, live webhooks, real-provider lost-response testing, production payments, refunds, disputes and tax calculation are not established by this release. No customer traction, official score or prize is claimed.

## Built with
Python; FastAPI; Pydantic; JavaScript; HTML; CSS; SQLite; PostgreSQL; Psycopg; HTTPX; Tenacity; PayPal Sandbox Orders v2; Qwen3.5-4B; llama.cpp/OpenAI-compatible local inference. PostgreSQL and local inference are optional for the credential-free simulation path. No sponsor-specific SDK prize usage is claimed.

## AI assistance and contribution disclosure
Codex substantially generated and revised implementation, tests, debugging changes, documentation and submission drafts, and assisted with automated validation and browser operation. It was not limited to proofreading. Runtime AI is a separate local Qwen model. The demonstration uses edited application footage and synthetic English narration generated with MiniMax speech-2.8-hd; the narrator is not the entrant's recorded voice. The footage begins with a saved model proposal and later shows an independent existing official Sandbox receipt.

The requested coding runtime was gpt-6-astra with ultra reasoning; the repository does not independently attest the served coding-model identity. No teammate contribution, unaided authorship, personal coding percentage or interview is asserted. The entrant must supply and review their actual decisions, implementation/review work, team membership and rights before any ownership or originality declaration.

## Links and testing fields
- Public source repository: https://github.com/Kuang-xianxin/scopepay — reviewed public commit `8aaf4e1309f66d58b3d50373898fe8e8d72d5e59`.
- Publicly visible YouTube video: https://www.youtube.com/watch?v=j9u4mM1TA-I — 138.666016 seconds, English narration; timed English subtitles uploaded per the publication receipt. This local check did not reverify public caption-track playback.
- Hosted demo: **NOT DEPLOYED**. Supported access is a local build described in docs/JUDGE-SETUP.md.
- Judge testing instructions: Python 3.12; install pinned dependencies; use .env.judge.example with scripts/run_local.py; run scripts/judge_scenario.py. This needs no Sandbox credentials, model download or PostgreSQL. It clearly uses simulation.
- Full AI/Sandbox access: **NEEDS-HUMAN** for an authorized local model endpoint and private Sandbox test access. Do not paste secrets into a public field or repository; the coordinator must verify a suitably private handoff mechanism. Existing successful integration is evidence, not a claim that judge access has already been delivered.
- Entrant/team identity, contribution, ownership, eligibility and any custom questions: **NEEDS-HUMAN**. No signature or acceptance is provided in this draft.
