## Server Environment

OS: Ubuntu 24.04.4 LTS (Noble Numbat)
Kernel: 6.8.0-85-generic x86_64
Python: 3.12.3
Docker: 29.2.1
RAM: 902MB total, ~470MB available
Disk: 28GB, 20GB free

## Phoenixd Status

Both running as Docker containers via `acinq/phoenixd` image (v0.7.2).
DO NOT touch these containers. They are already set up and funded.

### Proxy wallet (port 9740)
- Container: phoenixd
- Balance: 27,473 sats
- Channel state: Normal
- Inbound liquidity: 2,036,203 sats

### Test wallet (port 9741)
- Container: phoenixd-test
- Balance: 47,473 sats
- Channel state: Normal
- Inbound liquidity: 2,016,203 sats

## Phoenixd API Access

Both wallets use HTTP Basic auth with empty username and password from .env:

```bash
# Create invoice on proxy wallet
curl -s -u ":$PHOENIX_PASSWORD" -X POST http://localhost:9740/createinvoice \
  -d amountSat=1000 -d description="test"

# Pay invoice from test wallet
curl -s -u ":$PHOENIX_TEST_PASSWORD" -X POST http://localhost:9741/payinvoice \
  -d invoice="lnbc..."

# Check balances
curl -s -u ":$PHOENIX_PASSWORD" http://localhost:9740/getbalance
curl -s -u ":$PHOENIX_TEST_PASSWORD" http://localhost:9741/getbalance
```

## Project Directory

/home/abm/alittlebitofmoney/

Contains only phoenixd data dirs. All code goes here.

## Nginx

Not yet configured. Proxy should listen on 127.0.0.1:3000.
Nginx will be set up to reverse-proxy port 443 → 3000.
