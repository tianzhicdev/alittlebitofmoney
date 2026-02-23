# alittlebitofmoney proxy

Stateless Lightning-paid API proxy.

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 127.0.0.1 --port 3000
```

## Test

```bash
./scripts/test.sh
```

## Deploy

```bash
./deploy.sh local
./deploy.sh prod
```
