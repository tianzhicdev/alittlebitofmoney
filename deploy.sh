#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

load_env_defaults() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    return 0
  fi

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    if [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]]; then
      continue
    fi
    if [[ ! "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      continue
    fi

    local key="${line%%=*}"
    local value="${line#*=}"
    if [[ -n "${!key+x}" ]]; then
      continue
    fi

    if [[ ${#value} -ge 2 ]]; then
      if [[ "${value:0:1}" == "\"" && "${value: -1}" == "\"" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$key=$value"
  done < "$file"
}

load_env_defaults ".env.secrets"
load_env_defaults ".env"

MODE="${1:-}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new"

# ── target config ──────────────────────────────────────────────
#   prod  → lion    (aiforhire.xyz)
#   beta  → captain (alittlebitofmoney.com)
# ───────────────────────────────────────────────────────────────

resolve_target() {
  local env="$1"
  case "$env" in
    prod)
      T_HOST="lion"
      T_DIR="/root/alittlebitofmoney"
      T_PORT="3000"
      T_DOMAIN="aiforhire.xyz"
      T_SERVICE="alittlebitofmoney.service"
      ;;
    beta)
      T_HOST="captain"
      T_DIR="/home/abm/alittlebitofmoney"
      T_PORT="3000"
      T_DOMAIN="alittlebitofmoney.com"
      T_SERVICE="alittlebitofmoney.service"
      ;;
    *)
      echo "Unknown target: $env" >&2
      exit 1
      ;;
  esac
}

usage() {
  cat <<USAGE
Usage:
  ./deploy.sh local        # Run locally
  ./deploy.sh prod         # Deploy to aiforhire.xyz (lion)
  ./deploy.sh beta         # Deploy to alittlebitofmoney.com (captain)

SSH aliases "lion" and "captain" must be configured in ~/.ssh/config.
USAGE
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ssh_run() {
  local host="$1"
  local remote_cmd="$2"
  printf '%s\n' "$remote_cmd" | ssh $SSH_OPTS "$host" "bash -s"
}

rsync_run() {
  local host="$1"
  local target_dir="$2"

  local -a excludes=(
    --exclude ".git"
    --exclude "__pycache__"
    --exclude ".venv"
    --exclude "venv"
    --exclude "frontend/node_modules"
    --exclude "*.pyc"
    --exclude ".DS_Store"
    --exclude ".env"
    --exclude ".env.secrets"
    --exclude "*.log"
    --exclude "phoenixd-data"
    --exclude "phoenixd-test-data"
  )

  rsync -az --delete "${excludes[@]}" -e "ssh $SSH_OPTS" ./ "$host:$target_dir/"
}

deploy_local() {
  need_cmd python3
  local port="${PORT:-3000}"

  if [[ -d "frontend" ]]; then
    need_cmd npm
    npm --prefix frontend run build >/dev/null
  fi

  if [[ ! -d "venv" ]]; then
    python3 -m venv venv
  fi

  ./venv/bin/pip install -r requirements.txt

  pkill -f "uvicorn server:app --host 127.0.0.1 --port $port" >/dev/null 2>&1 || true
  nohup ./venv/bin/uvicorn server:app --host 127.0.0.1 --port "$port" > local-app.log 2>&1 < /dev/null &
  echo $! > .local-uvicorn.pid
  sleep 1

  echo "Local deploy complete"
  echo "App: http://127.0.0.1:$port"
  echo "Log: $ROOT_DIR/local-app.log"
}

deploy_remote() {
  local env="$1"
  need_cmd rsync
  need_cmd ssh

  resolve_target "$env"

  echo "─── deploying to $env ($T_DOMAIN via $T_HOST) ───"

  if [[ -d "frontend" ]]; then
    need_cmd npm
    echo "Building frontend bundle"
    (
      cd frontend
      npm ci
      npm run build
    )
  fi

  echo "Syncing code to $T_HOST:$T_DIR"
  rsync_run "$T_HOST" "$T_DIR"

  local remote_cmd
remote_cmd=$(cat <<REMOTE
set -euo pipefail
cd "$T_DIR"
if [[ ! -d "venv" ]]; then
  python3 -m venv venv
fi
./venv/bin/pip install -r requirements.txt >/dev/null

if systemctl cat $T_SERVICE >/dev/null 2>&1 && systemctl stop $T_SERVICE 2>/dev/null; then
  pkill -f "uvicorn server:app --host 127.0.0.1 --port $T_PORT" >/dev/null 2>&1 || true
  systemctl start $T_SERVICE
  systemctl is-active --quiet $T_SERVICE
  systemctl --no-pager --full status $T_SERVICE | sed -n '1,20p'
else
  pkill -f "uvicorn server:app --host 127.0.0.1 --port $T_PORT" >/dev/null 2>&1 || true
  sleep 1
  nohup ./venv/bin/uvicorn server:app --host 127.0.0.1 --port "$T_PORT" > app.log 2>&1 < /dev/null &
  echo \$! > .uvicorn.pid
  sleep 1
  PID=\$(cat .uvicorn.pid)
  ps -p "\$PID" -o pid= -o user= -o args=
fi

for attempt in \$(seq 1 20); do
  if curl -fsS "http://127.0.0.1:$T_PORT/api/v1/health" >/dev/null; then
    break
  fi
  if [[ "\$attempt" == "20" ]]; then
    echo "health check failed after retries" >&2
    exit 1
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$T_PORT/" >/dev/null
echo "$env deploy complete → $T_DOMAIN"
REMOTE
)

  ssh_run "$T_HOST" "$remote_cmd"

  echo "$env app on $T_HOST:$T_PORT (behind nginx) → $T_DOMAIN"
}

case "$MODE" in
  local)
    deploy_local
    ;;
  prod)
    deploy_remote prod
    ;;
  beta)
    deploy_remote beta
    ;;
  *)
    usage
    exit 1
    ;;
esac
