# alittlebitofmoney proxy

Stateless Lightning-paid API proxy with a Vite + React frontend.

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
uvicorn server:app --host 127.0.0.1 --port 3000
```

## Frontend (Vite dev server)

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api`, `/redeem`, `/openai`, and `/v1` to `http://127.0.0.1:3000`.

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

Full endpoint suite (all catalog endpoints):

```bash
./e2e-test-all.sh https://alittlebitofmoney.com
```

Useful flags:
- `VERBOSE=1` to print full request/response details.
- `STRICT_KEYWORD_MATCH=0` to relax keyword assertions on forwarded upstream errors.

## Deploy

```bash
./deploy.sh local
./deploy.sh prod
```
