# Human Setup Guide

You set up the VPS and Lightning wallets manually.
Then Claude Code gets SSH access to develop, test, and iterate against real Lightning.

---

## Phase 1: You Set Up the VPS (30 minutes)

### 1. Buy a VPS

Hetzner CAX11 (~$4/mo) or any Ubuntu 22.04+ box. 1GB RAM is enough.

Note:
- IP address
- Root password or SSH key

### 2. SSH in and install basics

```bash
ssh root@YOUR_VPS_IP

# Update system
apt update && apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install useful tools
apt install -y jq qrencode

# Create app user
adduser --disabled-password --gecos "" abm
usermod -aG docker abm

# Create project directory
mkdir -p /home/abm/alittlebitofmoney
chown abm:abm /home/abm/alittlebitofmoney
```

### 3. Start both phoenixd instances

```bash
cd /home/abm/alittlebitofmoney

# Create phoenixd directories
mkdir -p phoenixd-data phoenixd-test-data
chmod 777 phoenixd-data phoenixd-test-data

# Start proxy wallet (port 9740)
docker run -d \
  --name phoenixd \
  --restart unless-stopped \
  -v /home/abm/alittlebitofmoney/phoenixd-data:/phoenix/.phoenix \
  -p 127.0.0.1:9740:9740 \
  acinq/phoenixd

# Wait for initialization
sleep 15

# Start test wallet (port 9741)
docker run -d \
  --name phoenixd-test \
  --restart unless-stopped \
  -v /home/abm/alittlebitofmoney/phoenixd-test-data:/phoenix/.phoenix \
  -p 127.0.0.1:9741:9740 \
  acinq/phoenixd

sleep 15
```

### 4. Back up seed words

```bash
# Proxy wallet seed
docker logs phoenixd 2>&1 | grep -A 5 "seed"

# Test wallet seed
docker logs phoenixd-test 2>&1 | grep -A 5 "seed"
```

**WRITE BOTH DOWN ON PAPER. NOW.**

### 5. Get the HTTP passwords

```bash
# Proxy wallet password
cat /home/abm/alittlebitofmoney/phoenixd-data/phoenix.conf | grep http-password

# Test wallet password
cat /home/abm/alittlebitofmoney/phoenixd-test-data/phoenix.conf | grep http-password
```

Note both passwords.

### 6. Fund both wallets

```bash
PROXY_PW="your-proxy-password"

# Generate invoice + QR for proxy wallet
INVOICE=$(curl -s -u ":$PROXY_PW" -X POST http://localhost:9740/createinvoice \
  -d amountSat=50000 -d description="proxy funding" | jq -r '.serialized')
echo "$INVOICE"
qrencode -t ANSIUTF8 "$INVOICE"
```

**Scan QR with your phone wallet. Pay it.**

```bash
# Verify
curl -s -u ":$PROXY_PW" http://localhost:9740/getbalance | jq .
```

Same for test wallet:

```bash
TEST_PW="your-test-password"

INVOICE=$(curl -s -u ":$TEST_PW" -X POST http://localhost:9741/createinvoice \
  -d amountSat=20000 -d description="test funding" | jq -r '.serialized')
echo "$INVOICE"
qrencode -t ANSIUTF8 "$INVOICE"
```

**Scan and pay. Verify:**

```bash
curl -s -u ":$TEST_PW" http://localhost:9741/getbalance | jq .
```

### 7. Set up domain + Nginx + SSL (Cloudflare origin cert)

**In Cloudflare dashboard:**
1. DNS → A record: `alittlebitofmoney.com` → your VPS IP → **Proxied** (orange cloud)
2. SSL/TLS → Overview → set mode to **Full (strict)**
3. SSL/TLS → Origin Server → Create Certificate
   - Leave defaults (RSA 2048, 15 years)
   - Click Create
   - Copy the certificate PEM and private key PEM

**On the VPS:**

```bash
apt install -y nginx

# Paste your origin cert and key
mkdir -p /etc/ssl/cloudflare
nano /etc/ssl/cloudflare/origin.pem      # Paste certificate
nano /etc/ssl/cloudflare/origin-key.pem  # Paste private key
chmod 600 /etc/ssl/cloudflare/origin-key.pem

cat > /etc/nginx/sites-available/alittlebitofmoney << 'EOF'
server {
    listen 443 ssl;
    server_name YOUR_DOMAIN;

    ssl_certificate /etc/ssl/cloudflare/origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/origin-key.pem;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
    }
}

server {
    listen 80;
    server_name YOUR_DOMAIN;
    return 301 https://$host$request_uri;
}
EOF

sed -i 's/YOUR_DOMAIN/alittlebitofmoney.com/g' /etc/nginx/sites-available/alittlebitofmoney
ln -sf /etc/nginx/sites-available/alittlebitofmoney /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

No renewal ever. Origin cert lasts 15 years.

### 8. Firewall

```bash
ufw allow 22
ufw allow 80
ufw allow 443
ufw --force enable
```

### 9. Install Python deps

```bash
apt install -y python3-pip python3-venv
```

---

## Phase 2: Give Claude Code Access

Your VPS now has:
- Two funded Lightning wallets (ports 9740 and 9741)
- Nginx + SSL
- Docker + Node.js
- Domain resolving

### Env file for Claude Code:

```bash
# VPS access
VPS_IP=xxx.xxx.xxx.xxx
VPS_USER=root
VPS_PASSWORD=xxxxxxxx

# Lightning wallets (already running on VPS)
PHOENIX_URL=http://localhost:9740
PHOENIX_PASSWORD=xxxxxxxx
PHOENIX_TEST_URL=http://localhost:9741
PHOENIX_TEST_PASSWORD=xxxxxxxx

# Upstream API keys
OPENAI_API_KEY=sk-xxxxxxxx

# Server
PORT=3000
DOMAIN=alittlebitofmoney.com
```

### What Claude Code does:

1. SSHs into VPS
2. Writes proxy server code in /home/abm/alittlebitofmoney/
3. Creates venv, installs pip dependencies
4. Starts the proxy on port 3000
5. Runs test.sh — real LN payment, real OpenAI call
6. If test fails → reads error → fixes code → reruns
7. Iterates until everything works
8. Creates final PR

---

## Checklist Before Handing to Claude Code

- [ ] VPS running, SSH works
- [ ] Docker installed
- [ ] Python 3.12+ and python3-venv installed
- [ ] phoenixd on port 9740 with balance
- [ ] phoenixd-test on port 9741 with balance
- [ ] Both seed words backed up
- [ ] Nginx + SSL working
- [ ] Domain resolves to VPS
- [ ] Firewall: 22, 80, 443 only
- [ ] You have both phoenixd HTTP passwords
- [ ] You have OpenAI API key
