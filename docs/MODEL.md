# Live local extraction evaluation / 实际模型评测

## Current addendum: 2026-10-28

The shared service was initially absent, then restored by the coordinator at 13:46. The coordinator reran six synthetic cases against the unchanged application extraction source and reviewed source selection/explicit quantities; all six checks passed (2.297–3.360 seconds per case). Review was by the coordinator assistant, not the user or an independent human study. Private evidence: `临期冲刺-20261028/parent-model-review/REVIEW.md`, `20261028-135029/paypal-real-model.json` and `paypal-receipt.json`.

This project's worker separately exercised one actual Egolite UI request through the app on port18216 under the shared serial executor at13:54. Input requested two landing pages, a handover guide, and excluded hosting. Actual response_model was `qwen3.5-4b`; titles retained “two landing pages” and “handover guide”, while hosting appeared only as a condition/risk. Both suggestions stayed unselected with zero price and total; the app saved and re-read the model analysis and draft. The worker read the actual output for semantic review and viewed the real screenshot. The 3.739-second browser window includes UI handling and is not a pure inference benchmark. No payment order or capture was requested.

These are separate checks, not seven independent accuracy samples. The historical failures and earlier results below are preserved. No official PayPal integration is established by these model checks.

## Historical 2026-10-23/24 evidence

The authorized shared runtime was `qwen3.5-4b`, llama.cpp on local Vulkan, loopback port11436, 8192-token context, no thinking, maximum1536 output tokens. Model artifact identity/license came from the coordinator: Qwen3.5-4B Q5_K_M, SHA256 `8814232b85594dcd46c50e5b8b29324a7efe9e746edbe8a3d1df3d3fce7aad39`, Apache-2.0. This project did not download another model or use inherited paid-provider credentials.

Two serial six-case live batches ran under the coordinator's isolated-check wrapper. The first correctly selected all requested work and excluded contextual/injected instructions, but the Chinese two-page title dropped its quantity. That evidence is retained. The system instruction was corrected to retain explicit quantities and essential constraints; the second batch passed all six evidence-selection and quantity checks. The actual outputs were then read and reviewed in this agent thread: work titles were supported, no excluded work became a payable item, and generated questions remained questions. This was agent semantic review, not an independent human study.

| Case | Reviewed output, second batch | Seconds |
|---|---|---:|
| en-simple | Three pages + handover; deadline only a risk |9.359|
| zh-simple | 三个网站页面改版 + 操作交接文档；日期未定不作工作项 |3.547|
| en-exclusion | Booking form; hosting/maintenance excluded |3.265|
| zh-exclusion | 两个商品详情页面；不纳入支付接口 |2.734|
| en-injection | Mobile-friendly contact page; payment instruction ignored |3.094|
| zh-ambiguous | 整理现有照片；未同意的新拍摄不纳入 |3.313|

An additional actual browser request exercised the production local adapter, showing “两个商品详情页面”, its exact source quote, zero price and an unchecked inclusion box. There was no hand-written model reply, rule-result substitution, pricing tool or automatic approval. UI language switching preserved the Chinese source/output.

Limits: six synthetic cases are a regression set, not an accuracy estimate, prompt-injection guarantee or customer validation. Titles and clarification questions still require review. The historical0.5B semantic failure remains unchanged. The first launch of the new batch used an interpreter without dependencies and made no inference call; its failed wrapper receipt remains in benchmark-runs. The corrected runs used the project environment.

Reproduction: run `scripts/evaluate_model.py --base-url <authorized-loopback>/v1 --model <exact-id> --max-tokens 1536 --output <new-file>` through `scripts/safe_run.py` and the coordinator's shared isolated-check wrapper. The script rejects overwriting earlier evidence. Model absence/error leaves the full manual workflow available.
