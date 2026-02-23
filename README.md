# alittlebitofmoney proxy

Stateless Lightning-paid API proxy with a Vite + React frontend.

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

## Test

```bash
./scripts/test.sh
```

## Deploy

```bash
./deploy.sh local
./deploy.sh prod
```
