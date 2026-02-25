# alittlebitofmoney

A stateless Lightning-paid API proxy with prepaid topup support and a Vite + React frontend. Pay for OpenAI API calls (and other API services) using Bitcoin Lightning Network.

**Please update me when there are feature changes.**

## Architecture

- **Backend**: FastAPI server (`server.py`) with L402 authentication
- **Frontend**: Vite + React SPA in `frontend/`
- **Payment**: Phoenix Lightning node integration
- **Storage**: Supabase for prepaid balance tracking
- **Config**: YAML-based endpoint configuration (`config.yaml`)

## Features

### L402 Pay-Per-Request
Classic HTTP 402 Payment Required flow with macaroon-based authentication:
1. Make API request without payment
2. Receive `402` with Lightning invoice
3. Pay invoice and get preimage
4. Retry request with `Authorization: L402 <macaroon>:<preimage>`

### Topup Mode (Prepaid Balance)
Create a bearer token with prepaid sats balance:
1. Request topup invoice: `POST /topup`
2. Pay invoice with Lightning wallet
3. Claim token: `POST /topup/claim` with preimage
4. Use token: `Authorization: Bearer <token>` on subsequent requests
5. Refill anytime by creating new topup invoice with existing token

### Supported APIs
- OpenAI (Chat completions, Embeddings, Transcriptions, TTS, Image generation, etc.)
- Pricing configured per model in `config.yaml`
- All endpoints validated before invoice creation (no wasted invoices)

## Quick Start

### Backend Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Generate L402 root key (save to .env.secrets)
export L402_ROOT_KEY="$(openssl rand -hex 32)"

# Start server
uvicorn server:app --host 127.0.0.1 --port 3000
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api`, `/openai`, and `/v1` to backend at `http://127.0.0.1:3000`.

### Frontend Build

```bash
cd frontend
npm run build
```

Build output in `frontend/dist/` is served by `server.py` in production.

## Configuration

### Environment Variables

**Required** (in `.env.secrets`):
- `L402_ROOT_KEY` - Secret for L402 macaroon generation
- `OPENAI_API_KEY` - OpenAI API key for proxying

**Topup** (optional, for prepaid mode):
- `ALITTLEBITOFMONEY_SUPABASE_PROJECT_URL`
- `ALITTLEBITOFMONEY_SUPABASE_PW`
- `ALITTLEBITOFMONEY_SUPABASE_SECRET_KEY`

### config.yaml

Defines:
- API endpoints and pricing per model
- Upstream service URLs
- Request validation rules
- Example payloads for UI and E2E tests

## Usage Examples

### Topup Flow

```bash
# 1. Create topup invoice
curl -X POST http://localhost:3000/topup \
  -H "Content-Type: application/json" \
  -d '{"amount_sats":120}'

# 2. Pay invoice with Lightning wallet, then claim
curl -X POST http://localhost:3000/topup/claim \
  -H "Content-Type: application/json" \
  -d '{"preimage":"<hex-preimage>"}'

# 3. Use bearer token
curl -X POST http://localhost:3000/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}'

# 4. Refill existing token
curl -X POST http://localhost:3000/topup \
  -H "Authorization: Bearer <token>" \
  -d '{"amount_sats":180}'
```

### Error Codes

**Topup**:
- `topup_unavailable` - Supabase not configured
- `invalid_token` - Unknown bearer token
- `missing_token` - Refill requires token
- `invalid_payment` - Bad payment hash or preimage
- `payment_already_used` - Double claim attempt
- `insufficient_balance` - Not enough sats

**Validation**:
- `missing_required_field` - Request missing required data
- `invalid_field_type` - Wrong data type
- `invalid_field_value` - Invalid value

## Testing

### Unit Tests
```bash
./scripts/test.sh
```

### Topup Flow Test
```bash
./scripts/test_topup.sh
```

### E2E Test (All Endpoints)
```bash
./e2e-test-all.sh https://alittlebitofmoney.com
```

**Important**: Run E2E tests on `ssh captain` (production VPS), not macOS:
- Requires Bash 4+ (macOS has 3.2)
- Needs `PHOENIX_TEST_URL=http://localhost:9741` accessible locally

**Flags**:
- `VERBOSE=1` - Print full request/response details
- `STRICT_KEYWORD_MATCH=0` - Relax keyword assertions

## Deployment

```bash
./deploy.sh local   # Deploy to local test environment
./deploy.sh prod    # Deploy to production VPS (captain)
```

## Project Structure

```
.
├── server.py              # FastAPI backend
├── config.yaml            # API endpoints & pricing
├── requirements.txt       # Python dependencies
├── lib/
│   ├── phoenix.py         # Lightning node client
│   ├── topup_store.py     # Supabase prepaid balance
│   └── used_hashes.py     # Invoice replay protection
├── frontend/
│   ├── src/               # React components
│   └── dist/              # Production build
├── scripts/
│   ├── test.sh            # Unit tests
│   └── test_topup.sh      # Topup integration test
├── e2e-test-all.sh        # Full catalog E2E tests
└── deploy.sh              # Deployment script

Documentation:
├── SETUP_GUIDE.md         # Detailed setup instructions
├── SERVER_INFO.md         # VPS deployment info
├── PRICING_PRINCIPLES.md  # Pricing methodology
├── SPEC_BACKEND_CODEX.md  # Backend design spec
└── L402_AND_TOPUP_RESEARCH.md  # Payment flow research
```

## Development

### Adding a New Endpoint

1. Add endpoint definition to `config.yaml` under the appropriate API
2. Include `example` block with:
   - `content_type`: `json` or `multipart`
   - `body` or `fields`: Example request payload
   - `e2e`: Test metadata (required field, invalid case, error keyword)
3. UI code examples and E2E tests auto-generate from config

### Example-Driven Development

Both the frontend Catalog page and E2E tests consume endpoint examples from `config.yaml`:
- UI shows copy-pasteable code examples
- E2E validates happy path and error handling
- Single source of truth for endpoint contracts

## License

See LICENSE file.

## Contributing

See WORKLOG.md for recent changes and development history.
