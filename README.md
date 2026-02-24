# alittlebitofmoney proxy

Stateless Lightning-paid API proxy with a Vite + React frontend.

## Topup Mode (Phase 3)

Prepaid balance via Supabase-backed bearer tokens:
- `POST /topup` with `{ "amount_sats": <int> }` returns `402` + invoice.
- `POST /topup/claim` with `{ "preimage": "<hex>" }` returns `{ token, balance_sats }`.
- Use `Authorization: Bearer <token>` on API calls to spend balance.

Environment variables for topup:
- `ALITTLEBITOFMONEY_SUPABASE_PROJECT_URL`
- `ALITTLEBITOFMONEY_SUPABASE_PW`
- `ALITTLEBITOFMONEY_SUPABASE_SECRET_KEY` (stored for compatibility, currently unused by DB-path implementation)

## Request Validation (before invoice)

JSON endpoints are pre-validated before issuing an invoice. If required fields are missing
or clearly invalid, the server returns HTTP `400` and **does not** create a Lightning invoice.

Error codes:
- `missing_required_field`
- `invalid_field_type`
- `invalid_field_value`

## Backend (API server)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# one-time secret for L402 macaroons (persist this in .env)
export L402_ROOT_KEY="$(openssl rand -hex 32)"
uvicorn server:app --host 127.0.0.1 --port 3000
```

## Frontend (Vite dev server)

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api`, `/openai`, and `/v1` to `http://127.0.0.1:3000`.

## Frontend build

```bash
cd frontend
npm run build
```

Build output is written to `frontend/dist/` and served by `server.py` in production.

## Example-Driven UI + E2E

Endpoint examples are defined in `config.yaml` under each endpoint `example` block.

- UI code examples (Catalog page) are generated from `example`.
- End-to-end tests (`e2e-test-all.sh`) also consume `example` (and `example.e2e` overrides) from `/api/catalog`.

When adding a new endpoint, always add:
- `example.content_type` (`json` or `multipart`)
- `example.body` (for JSON) or `example.fields` (for multipart)
- `example.e2e` metadata for test-specific invalid case/expected keyword

## Test

```bash
./scripts/test.sh
```

Topup flow (invoice, claim, bearer, refill):

```bash
./scripts/test_topup.sh
```

Full endpoint suite (all catalog endpoints):

```bash
./e2e-test-all.sh https://alittlebitofmoney.com
```

Important: run `e2e-test-all.sh` on `ssh captain` (the VPS), not macOS local shell.
- It requires Bash 4+ (`mapfile`), while macOS default Bash is 3.2.
- It expects `PHOENIX_TEST_URL=http://localhost:9741` to be reachable from the same machine running the test.

Useful flags:
- `VERBOSE=1` to print full request/response details.
- `STRICT_KEYWORD_MATCH=0` to relax keyword assertions on forwarded upstream errors.

## Deploy

```bash
./deploy.sh local
./deploy.sh prod
```
