# alittlebitofmoney.com — Step 1 MVP Spec

## What This Is

A stateless API proxy that accepts Lightning payments per request. No accounts, no database, no auth. Client sends a request, gets a Lightning invoice, pays it, gets the API response.

## Architecture

```
Client
  │
  ├─ 1. POST /openai/v1/chat/completions  { body }
  ├─ 2. Server returns 402 + invoice + payment_hash
  ├─ 3. Client pays invoice with any LN wallet
  ├─ 4. GET /redeem?preimage=...
  ├─ 5. Server verifies, proxies stored request, returns response
  │
  ▼
Done. No state saved.
```

## Tech Stack

- **Runtime**: Python 3.12+
- **Framework**: FastAPI + uvicorn
- **HTTP Client**: httpx (async, for phoenixd + upstream calls)
- **Lightning**: phoenixd (localhost:9740)
- **Deployment**: VPS with systemd or direct run

## Project Structure

```
alittlebitofmoney/
├── config.yaml
├── server.py
├── lib/
│   ├── phoenix.py
│   └── invoice_store.py
├── public/
│   └── index.html
├── scripts/
│   └── test.sh
├── requirements.txt
├── .env
└── README.md
```

## Config (config.yaml)

Everything priced in sats. Backend knows nothing about USD.

```yaml
server:
  port: 3000

phoenix:
  url: "http://phoenixd:9740"

margin_percent: 5
min_sats: 100
invoice_expiry: 600

apis:
  openai:
    name: "OpenAI"
    upstream_base: "https://api.openai.com"
    api_key_env: "OPENAI_API_KEY"
    auth_header: "Authorization"
    auth_prefix: "Bearer "
    endpoints:
      - path: "/v1/chat/completions"
        method: "POST"
        price_type: "per_model"
        description: "Chat completions"
        models:
          gpt-4o-mini:      300
          gpt-4o:           2000
          gpt-4.5-preview:  10000
          _default:         5000

      - path: "/v1/images/generations"
        method: "POST"
        price_type: "flat"
        price_sats: 4000
        description: "DALL-E image generation"

      - path: "/v1/audio/speech"
        method: "POST"
        price_type: "flat"
        price_sats: 2000
        description: "Text-to-speech"

      - path: "/v1/audio/transcriptions"
        method: "POST"
        price_type: "flat"
        price_sats: 1000
        description: "Whisper transcription"

      - path: "/v1/embeddings"
        method: "POST"
        price_type: "flat"
        price_sats: 100
        description: "Text embeddings"
```

## .env

```bash
PHOENIX_PASSWORD=your-phoenixd-http-password
PHOENIX_TEST_PASSWORD=your-test-phoenixd-http-password
OPENAI_API_KEY=sk-xxxxxxxx
PORT=3000
```

## Core Flow

### 1. Request comes in (no payment proof)

- Match path to config endpoint
- Determine price:
  - `price_type: "flat"` → use `price_sats`
  - `price_type: "per_model"` → read `model` from request body, look up in `models` map, use `_default` if not listed
- Apply margin: `total = math.ceil(price * (1 + margin_percent / 100))`
- Enforce minimum: `total = max(total, min_sats)`
- Call phoenixd `POST /createinvoice`
- Store invoice in memory Map
- Return 402:

```json
{
  "status": "payment_required",
  "invoice": "lnbc...",
  "payment_hash": "abc123...",
  "amount_sats": 2100,
  "expires_in": 600
}
```

Headers:
```
X-Lightning-Invoice: lnbc...
X-Payment-Hash: abc123...
X-Price-Sats: 2100
```

### 2. Client pays invoice externally

### 3. Client retries with proof

```
GET /redeem?preimage=789xyz...
```

### 4. Server verifies and proxies

- Verify: `sha256(preimage) === payment_hash`
- Check: payment_hash in store and not used
- Mark as used
- Proxy using the **stored request_body and endpoint from step 1**
- Client cannot change the request — the payment_hash maps to a fixed request
- Return upstream response

## API Routes

```
POST /{api_name}/*             → Returns 402 + invoice (always)
GET  /redeem                  → Verify payment, proxy stored request, return response
     Query params: preimage={hex}
GET  /api/catalog              → List APIs + prices in sats
GET  /health                   → Server + phoenixd status
GET  /                         → Static landing page
```

Note: the first call (POST) ALWAYS returns 402. It never proxies directly.
The second call is always to /redeem. Clean separation.

## Invoice Store (lib/invoice_store.py)

In-memory dict. No database.

```
invoices: dict[str, {
  "invoice": str,
  "api_name": str,
  "endpoint_path": str,
  "amount_sats": int,
  "request_body": dict,
  "created_at": float,
  "status": "pending" | "used"
}]
```

Cleanup every 5 min, delete entries older than 30 min.
Keep Set of used payment_hashes for 1 hour for replay prevention.

## Phoenixd Client (lib/phoenix.py)

```
POST /createinvoice  { amountSat, description }
  → { serialized, paymentHash }

GET /payments/incoming/{paymentHash}
  → { isPaid, preimage, ... }
```

Auth: HTTP Basic with password from .env.

Primary verification: `sha256(preimage) === payment_hash` (no phoenixd call needed).

## Error Responses

```json
{ "error": { "code": "...", "message": "..." } }
```

- `payment_required` (402)
- `invalid_payment` (400)
- `payment_already_used` (400)
- `invoice_expired` (410)
- `api_not_found` (404)
- `upstream_error` (502)
- `phoenix_unavailable` (503)

## Deployment

Phoenixd wallets are already running on the VPS (set up manually, see SETUP_GUIDE.md).
The proxy is a Python app. No Docker needed for the proxy itself.

```bash
cd /home/abm/alittlebitofmoney
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 3000
```

The proxy connects to phoenixd on localhost:9740. Nginx fronts it on port 443.

## VPS Setup

VPS is set up manually before Claude Code starts. See SETUP_GUIDE.md.
Claude Code gets SSH access and develops directly on the VPS against live phoenixd instances.

## Landing Page

Static HTML. The ONLY place USD appears — client-side JS fetches a rate for display. Backend never touches USD.

Shows: available APIs, prices in sats, ~USD equivalent, curl example, "no signup required."

## Testing

Two phoenixd instances run on the VPS: one for the proxy (receives payments), one for testing (pays invoices). You can't pay your own invoices on Lightning — you need a separate wallet.

### Two phoenixd instances on the VPS

- `phoenixd` on port 9740: proxy wallet (receives payments)
- `phoenixd-test` on port 9741: test wallet (pays invoices)

Both running as Docker containers, already funded.

### Test Script (scripts/test.sh)

Fully automated. No human intervention needed.

```bash
#!/bin/bash
set -e

BASE_URL="${1:-http://localhost:3000}"
TEST_PHOENIX="http://localhost:9741"
TEST_PHOENIX_PW="$(cat .env.test | grep PHOENIX_TEST_PASSWORD | cut -d= -f2)"

echo "=== Step 1: Request API call ==="
RESPONSE=$(curl -s -X POST "$BASE_URL/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello in 5 words"}],
    "max_tokens": 20
  }')

echo "$RESPONSE" | jq .

INVOICE=$(echo "$RESPONSE" | jq -r '.invoice')
AMOUNT=$(echo "$RESPONSE" | jq -r '.amount_sats')

echo ""
echo "=== Step 2: Pay invoice ($AMOUNT sats) via test wallet ==="
PAY_RESPONSE=$(curl -s -X POST "$TEST_PHOENIX/payinvoice" \
  -u ":$TEST_PHOENIX_PW" \
  -d "invoice=$INVOICE")

echo "$PAY_RESPONSE" | jq .

PREIMAGE=$(echo "$PAY_RESPONSE" | jq -r '.paymentPreimage')

echo ""
echo "=== Step 3: Redeem ==="
RESULT=$(curl -s "$BASE_URL/redeem?preimage=$PREIMAGE")

echo "$RESULT" | jq .

echo ""
echo "=== Done ==="
```

### .env includes test wallet password

```bash
PHOENIX_PASSWORD=xxx          # Proxy wallet
PHOENIX_TEST_PASSWORD=xxx     # Test wallet (for automated testing)
```

Both passwords are extracted from their respective phoenixd instances during setup.

## What NOT To Build

- No database
- No user accounts
- No USD in backend
- No price API dependencies
- No signup/login
- No dashboard
- No rate limiting (payment IS the rate limit)
- No SDK
- No frontend framework

## What Comes Next (Step 2)

- Database + accounts + API keys
- Prepaid balances
- Multi-crypto deposits via SideShift/Boltz
- Per-token billing from upstream response `usage` field
- Seller accounts
