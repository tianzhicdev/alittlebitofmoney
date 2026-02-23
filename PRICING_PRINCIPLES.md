# Pricing Principles

A reference document for setting and adjusting prices on alittlebitofmoney.com.

## 1. Never Lose Money on Average

The goal is not to profit on every single request. The goal is to profit on the aggregate.

A flat-rate pricing model means some requests cost us more than we charge (a user sends 8K input tokens and gets 4K output tokens) and some cost us far less (a user sends "say hi" and gets 12 tokens back). The law of averages works in our favor: most requests are short.

**The rule:** price each model so that the worst realistic case (max input + max output at our caps) still leaves at least 2x margin. If the absolute worst case (a user somehow maximizes everything) dips below 1x, that's acceptable as long as the average case is 3x+.

**Why this works:** we enforce max_output_tokens and max_request_bytes. These hard caps bound the tail risk. A user cannot send a 100K token prompt — we reject it at 32KB. A user cannot generate 50K output tokens — we cap at 4000. The worst case is a known, finite number.

**When to worry:** if analytics show the average margin dropping below 2x for any model, raise the price or lower the caps.

## 2. Account for Attrition

Not every invoice gets paid. Not every paid invoice gets redeemed. This is free money.

**Expected attrition rates:**

| Stage | Drop-off | Why |
|---|---|---|
| Invoice issued → paid | 30-50% | User was browsing, testing, comparing prices. Invoices expire in 10 minutes. |
| Paid → redeemed | 5-10% | User's script crashes, they lose the preimage, they close the tab. |
| Redeemed → upstream succeeds | 1-2% | OpenAI rate limit, model down, timeout. We keep the sats regardless. |

**Net effect:** for every 100 invoices issued, roughly 50 get paid, ~45 get redeemed, and ~44 result in a successful upstream call. We collect revenue on ~50 but only incur upstream costs on ~44. That's a built-in ~12% revenue boost on top of per-request margins.

**Ethical note on failed redemptions:** if the upstream call fails due to our fault (our server crashes, our OpenAI key is revoked), we should eat the cost. If it fails due to OpenAI being down or the user's request being invalid, we keep the sats — we did our job, the upstream didn't. Document this policy clearly.

**What we should never do:** artificially inflate attrition. Invoices should be easy to pay. Redemption should be easy. We make money by being useful, not by being confusing.

## 3. The Lightning Fee Floor

Lightning payments under ~10 sats are economically irrational. Routing fees can be 1-3 sats, and wallet apps often add their own margin. A 5-sat payment where 3 sats go to routing is a 60% fee — terrible UX.

**Minimum practical price: 20 sats.** Below this, the Lightning fee becomes a noticeable percentage of the total and users feel ripped off by the network, not by us.

This means dirt-cheap upstream calls (embeddings at $0.0001) still get priced at 10-20 sats. That's a high multiplier but the absolute cost is fractions of a cent. No one cares about 10x margin on a $0.007 charge. They care about 10x margin on a $0.50 charge.

**Rule of thumb:** margin percentage matters less as absolute price decreases. A 20x margin on a 10-sat call is fine. A 20x margin on a 500-sat call is gouging.

## 4. Price in Sats, Display in Cents

Sats are the unit of account. All pricing logic, config files, invoices, and storage use sats. USD is a display convenience only.

**Why:** if we priced in USD and converted to sats at payment time, BTC volatility would create arbitrage windows. A user could request an invoice when BTC is high (cheap in sats), wait for BTC to drop, then pay fewer real-dollars than intended. By pricing in sats, the price is the price.

**USD display:** fetch BTC/USD from CoinGecko every 5 minutes. Show cents alongside sats in the catalog and docs. This helps users who think in dollars understand what they're paying. But the invoice is always in sats.

**Volatility response:** if BTC moves ±30% from our pricing baseline, review all prices. We don't need to auto-adjust — manual review monthly is fine for the MVP. Automated repricing is a step 2 feature.

## 5. Price the Capability, Not the Cost

Users don't know or care what OpenAI charges per token. They care what it costs them to get a response. Our pricing should reflect the value to the user, not our cost.

**Example:** generating an image is "worth" more to a user than a text completion, even if the upstream cost is similar. An image is a tangible deliverable. A chat response is ephemeral. Price images higher.

**Example:** GPT-5.2 and GPT-5.1 have similar upstream costs but GPT-5.2 is the newest, most capable model. Users will pay more for it. Price it higher.

**Example:** embeddings are a commodity. Price them at floor. Nobody shops for the cheapest embedding endpoint — but they do shop for the cheapest GPT-5 access.

**Don't be clever:** avoid complex pricing tiers, quality multipliers, or dynamic pricing. One model, one price, one cap. The simplicity is the product.

## 6. Bound the Worst Case, Don't Optimize the Average

Every pricing decision should be driven by: "what's the most expensive request a user can send within our caps, and can we survive it?"

**Caps we enforce:**

| Cap | Purpose |
|---|---|
| `max_request_bytes` (32KB default) | Bounds input token cost. 32KB ≈ 8K tokens worst case. |
| `max_output_tokens` (4000 default) | Bounds output token cost. Set per model. |
| `n=1` for images | One image per payment. Prevents 10x cost on a single invoice. |
| `max_request_bytes` for audio (10MB) | Bounds transcription cost. 10MB ≈ 10 min audio. |
| `max_request_bytes` for TTS (16KB) | Bounds TTS cost. 16KB ≈ 4000 chars. |

**The math for any model:**

```
worst_case_cost = (max_input_tokens × input_price_per_token)
                + (max_output_tokens × output_price_per_token)

our_price_sats must be > worst_case_cost / sats_to_usd
```

If this inequality holds, we cannot lose money on any single request. If it doesn't hold for extreme edge cases but holds for the 95th percentile, that's acceptable — see principle 1.

## 7. Competitive Positioning

We are not competing on price with OpenAI direct. We can't — we're a reseller with a margin. Our users are paying a premium for:

1. **Access** — no credit card, no KYC, no country restrictions
2. **Privacy** — no account, no identity, no audit trail
3. **Simplicity** — no API key management, no billing dashboard, no invoices

The premium should feel reasonable, not extractive. Guidelines:

| Upstream cost | Our markup | Reasoning |
|---|---|---|
| < $0.01 | 5-20x | Absolute cost is trivial. User pays 1-2 cents. Nobody notices. |
| $0.01 - $0.05 | 3-5x | Mid-range. User pays 5-25 cents. Should feel fair. |
| $0.05 - $0.20 | 2-3x | Expensive calls. User pays 15-60 cents. Premium is noticeable. |
| > $0.20 | 1.5-2x | High-value calls. User pays 40+ cents. Keep markup tight or users find alternatives. |

**Who we're actually competing with:** not OpenAI. We compete with the friction of not having access at all. Our real competitor is "I can't use this API because my country/card/identity doesn't work." Against that, 3x markup is nothing.

## 8. Pricing New Endpoints

When adding a new API endpoint, follow this checklist:

1. **Find the upstream cost.** Check the provider's pricing page. Calculate worst-case cost at our caps.
2. **Set the cap.** What's the maximum reasonable request for this endpoint? Set `max_request_bytes` and any model-specific output limits.
3. **Calculate the floor.** `worst_case_upstream_cost / sat_value × 2 = minimum_price_sats`. Round up.
4. **Apply the Lightning floor.** If minimum_price_sats < 20, set it to 20.
5. **Apply the value multiplier.** Is this endpoint high-perceived-value (images, audio, video)? Add margin. Is it commodity (embeddings, moderation)? Keep it at floor.
6. **Sanity check in cents.** Does the price feel reasonable to a human? Would you pay this? If not, adjust.
7. **Add to config.yaml and /api/catalog.** Ship it.

## 9. When to Change Prices

**Raise prices when:**
- BTC drops 30%+ and margins compress below 2x
- Upstream provider raises their prices
- A specific model's average request cost is approaching our price (analytics show margin < 2x)

**Lower prices when:**
- BTC rises 30%+ and our USD-equivalent prices look expensive
- Upstream provider cuts their prices
- We want to drive volume on an underused endpoint
- A competitor (if any emerge) undercuts us

**Never change prices because:**
- A single request lost money (expected, see principle 1)
- A user complains without data (anecdotes aren't analytics)
- We "feel like" prices are wrong (use the math)

## 10. Future: Per-Token Pricing (Step 2)

Once we add accounts and prepaid balances, we can switch from flat-rate to per-token billing:

1. User deposits 10,000 sats into their account
2. User sends a request (no invoice needed — deduct from balance)
3. After upstream responds, read the `usage` field from OpenAI's response
4. Calculate actual cost: `(prompt_tokens × input_rate) + (completion_tokens × output_rate)`
5. Apply our markup (e.g., 2x)
6. Deduct from balance

This eliminates the worst-case pricing problem entirely. Users pay for exactly what they use. But it requires accounts, a database, and trust (they trust us with their balance). That's step 2. The flat-rate model is step 1 and it works.