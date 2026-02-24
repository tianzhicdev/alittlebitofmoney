# L402 Compatibility & Topup Feature: Research & Direction

## 1. What the System Does Today

Current flow:

```
POST /openai/v1/chat/completions  (with request body)
  → 402 + JSON { invoice, payment_hash, amount_sats }
  → headers: X-Lightning-Invoice, X-Payment-Hash, X-Price-Sats

User pays invoice → gets preimage

GET /redeem?preimage=<hex>
  → server hashes preimage → looks up stored request → proxies to OpenAI → returns response
```

The server stores the entire request body in-memory (InvoiceStore), keyed by payment_hash. The redeem step replays this stored request to the upstream API. This is a 2-endpoint flow: one to submit + get invoice, another to redeem.

## 2. What L402 Actually Is

L402 is an HTTP authentication scheme built on two primitives:

```
Client → POST /resource (no auth)
Server → 402 Payment Required
         WWW-Authenticate: L402 macaroon="<base64>", invoice="lnbc..."

Client pays invoice → gets preimage (32 random bytes)

Client → POST /resource (re-sends same request)
         Authorization: L402 <base64_macaroon>:<hex_preimage>
Server → 200 OK + response
```

**Macaroon**: A cryptographically signed token (HMAC-chained). The server creates it with a secret root key. Caveats (key=value restrictions) are chained into the signature. Anyone can *add* caveats (making it more restrictive), but nobody can remove or modify existing ones without the root key. The server verifies it by recomputing the HMAC chain.

**Preimage**: 32 random bytes. Just raw entropy. Contains no amount, no metadata, nothing. The *invoice* (the `lnbc...` string) encodes the amount, but the invoice stays on the payment side — the wallet sees it, pays it, hands back the raw preimage. By verification time, the invoice is gone.

**Together**: The macaroon proves the server issued it. The preimage proves the linked invoice was paid. `sha256(preimage) == payment_hash` embedded in the macaroon.

## 3. The Gap Between Current System and L402

| Aspect | Current system | L402 spec |
|--------|---------------|-----------|
| 402 response | JSON body with invoice | `WWW-Authenticate` header with macaroon + invoice |
| Client auth | `GET /redeem?preimage=...` | `Authorization: L402 <mac>:<preimage>` on same endpoint |
| Request storage | Server stores request body in-memory | Client re-sends request with auth header |
| Verification | DB lookup (InvoiceStore) | Cryptographic (macaroon signature + preimage hash) |

L402 clients (AI agents, L402 libraries, satring.com-compatible tools) cannot talk to the current API without a custom adapter.

## 4. Why Macaroons Are Necessary (Not Just for Compatibility)

Since this service has **variable pricing based on request content** (different models cost different amounts), the macaroon must encode the paid amount. Without it, there's no way to verify what was paid at request time — the preimage is just 32 random bytes and carries no amount information.

### Required macaroon caveats

```
payment_hash = <hex>       # links macaroon to specific invoice/preimage
amount_sats = <int>        # what was charged for this payment
```

This is minimal. No endpoint restrictions, no expiry caveats, no user IDs. Just enough to make stateless verification work for variable-price endpoints.

### Verification flow (4 steps)

```
Client sends: Authorization: L402 <base64_macaroon>:<hex_preimage>
              Body: { "model": "gpt-4o-mini", "messages": [...] }

Step 1: Verify macaroon signature (HMAC chain with root key)
        → proves the server issued this macaroon with these exact caveats
        → forgery impossible without root key

Step 2: Verify sha256(preimage) == payment_hash from macaroon
        → proves this preimage belongs to this specific macaroon
        → cross-macaroon preimage swapping impossible

Step 3: Check payment_hash not in used_hashes set
        → prevents replay of the same payment
        → in-memory set with TTL, lightweight

Step 4: Re-price the request body, check price <= amount_sats from macaroon
        → prevents model-switching (pay for cheap, use expensive)
        → user can overpay (their problem, not ours)
```

### Attack analysis

| Attack | How it fails |
|--------|-------------|
| **Forge macaroon** with `amount_sats = 10000` | Step 1: HMAC verification fails without root key |
| **Modify caveat** in existing macaroon | Step 1: HMAC chain breaks, signature invalid |
| **Pay cheap invoice**, use expensive macaroon's preimage | Step 2: `sha256(cheap_preimage) != expensive_payment_hash` |
| **Replay** a previously used macaroon+preimage | Step 3: payment_hash already in used set |
| **Pay for gpt-4o-mini**, re-send with `model: gpt-4.5` | Step 4: `price(gpt-4.5) > amount_sats` in macaroon |
| **Pay for expensive model**, use cheap model | All steps pass. User overpays. Their problem. |

## 5. Architecture Change: Drop Request Storage

Since the client re-sends the full request with the Authorization header, the server no longer needs to store request bodies.

**Before (InvoiceStore)**:
```
{ payment_hash → InvoiceRecord(invoice, api_name, endpoint_path,
                                amount_sats, request_bytes,
                                request_content_type, created_at, status) }
```

**After (used hashes set)**:
```
{ payment_hash }  # just a set with TTL
```

This eliminates:
- In-memory request body storage
- TTL/cleanup of stored requests
- The `/redeem` endpoint entirely
- The InvoiceStore class (replace with a simple UsedHashSet)

The proxy endpoint handles everything: no auth → 402, valid L402 auth → verify + proxy.

### New flow

```
POST /openai/v1/chat/completions
  Headers: (no Authorization)
  Body: { "model": "gpt-4o-mini", "messages": [...] }

→ Server prices the request (10 sats)
→ Server creates Lightning invoice (10 sats)
→ Server creates macaroon with caveats:
    payment_hash = <hash from invoice>
    amount_sats = 10

→ 402 Payment Required
  WWW-Authenticate: L402 macaroon="<base64>", invoice="lnbc..."
  Body: { "status": "payment_required", "invoice": "lnbc...",
          "payment_hash": "...", "amount_sats": 10 }

--- client pays invoice via Lightning wallet, gets preimage ---

POST /openai/v1/chat/completions
  Headers: Authorization: L402 <base64_macaroon>:<hex_preimage>
  Body: { "model": "gpt-4o-mini", "messages": [...] }

→ Server runs 4-step verification
→ Server proxies to OpenAI
→ 200 OK (upstream response)
```

## 6. Topup Feature: Prepaid Balance

Orthogonal to L402 pay-per-request. Provides a second payment mode for reduced fees and lower latency.

### Flow

```
POST /topup
  Body: { "amount_sats": 10000 }
→ 402 + Lightning invoice for 10000 sats

--- user pays ---

POST /topup/claim
  Body: { "preimage": "<hex>" }
→ 200 { "token": "abl_abc123...", "balance_sats": 10000 }
```

API calls with prepaid balance:
```
POST /openai/v1/chat/completions
  Headers: Authorization: Bearer abl_abc123...
  Body: { ... }
→ Server checks token → deducts cost from balance → proxies → returns response
```

Refill existing token:
```
POST /topup
  Headers: Authorization: Bearer abl_abc123...
  Body: { "amount_sats": 5000 }
→ 402 + invoice

--- pay ---

POST /topup/claim
  Body: { "preimage": "<hex>", "token": "abl_abc123..." }
→ 200 { "token": "abl_abc123...", "balance_sats": 15000 }
```

### Supabase schema

```sql
create table accounts (
  id uuid primary key default gen_random_uuid(),
  token_hash text unique not null,      -- sha256 of the bearer token
  balance_sats bigint not null default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table topup_invoices (
  payment_hash text primary key,
  account_id uuid references accounts(id),  -- null for new accounts
  amount_sats bigint not null,
  status text not null default 'pending',    -- pending | paid | expired
  created_at timestamptz default now()
);

create table usage_log (
  id bigserial primary key,
  account_id uuid references accounts(id),
  endpoint text not null,
  amount_sats bigint not null,
  created_at timestamptz default now()
);
```

Token generated server-side (`secrets.token_urlsafe(32)`), stored as sha256 hash.

## 7. How L402 and Topup Coexist

The proxy endpoint checks for auth in order:

```python
async def handle_request(request):
    auth = request.headers.get("Authorization", "")

    if auth.startswith("Bearer "):
        # Topup mode: check token, check balance, deduct, proxy
        ...
    elif auth.startswith("L402 "):
        # L402 mode: 4-step verification, proxy
        ...
    else:
        # No auth: price request, create invoice + macaroon, return 402
        ...
```

The 402 response advertises both payment methods:
```
HTTP/1.1 402 Payment Required
WWW-Authenticate: L402 macaroon="...", invoice="lnbc..."
X-Topup-URL: /topup
```

## 8. Implementation Order

### Phase 1: L402 compatibility
- Add `pymacaroons` dependency
- Generate root key (random secret, stored in `.env`)
- On 402: create macaroon with `payment_hash` + `amount_sats` caveats
- Return `WWW-Authenticate: L402 macaroon="...", invoice="..."` header
- Accept `Authorization: L402 <mac>:<preimage>` — run 4-step verification, proxy upstream
- Replace InvoiceStore with simple UsedHashSet (in-memory, TTL)
- Keep `/redeem` temporarily as legacy fallback
- Keep JSON body in 402 response for backwards compatibility

### Phase 2: Deprecate legacy
- Remove `/redeem` endpoint
- Remove InvoiceStore class
- Update frontend docs and demo scripts

### Phase 3: Topup with Supabase
- Add Supabase client
- Create 3 tables (accounts, topup_invoices, usage_log)
- Add `/topup` and `/topup/claim` endpoints
- Add `Bearer` token auth path in proxy endpoint
- Balance deduction with row-level locking

### Phase 4: Ecosystem
- Register on satring.com
- Add `/.well-known/l402` discovery endpoint
- Update documentation with L402 client examples

## 9. Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Use macaroons? | Yes | Required for stateless amount verification, not just compatibility |
| Macaroon caveats | `payment_hash` + `amount_sats` | Minimum needed for variable-price endpoints |
| Macaroon library | `pymacaroons` | Lightweight, well-established |
| Request body storage | Eliminated | Client re-sends request; macaroon encodes paid amount |
| Replay protection | In-memory used_hashes set with TTL | Lightweight, same pattern as current `_used_hashes` |
| Topup DB | Supabase (3 tables) | Minimal schema, persistent |
| Topup token format | `Bearer abl_<random>` | Standard bearer auth, Lightning-funded |
| Auth coexistence | `Bearer` = topup, `L402` = pay-per-request, none = 402 | Single endpoint, multiple payment modes |
| L402 Python library (Fewsats) | Don't use | Too opinionated; protocol is simple enough (~100 lines) |
