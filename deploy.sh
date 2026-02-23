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
PORT="${PORT:-3000}"
REMOTE_DIR="${REMOTE_DIR:-/home/abm/alittlebitofmoney}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new"

usage() {
  cat <<USAGE
Usage:
  ./deploy.sh local
  ./deploy.sh prod

Env vars used for prod:
  VPS_IP (required)
  VPS_USER (required)
  VPS_PASSWORD (optional, requires sshpass)
  REMOTE_DIR (optional, default: /home/abm/alittlebitofmoney)
  PORT (optional, default: 3000)
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

  if [[ -n "${VPS_PASSWORD:-}" ]]; then
    need_cmd sshpass
    printf '%s\n' "$remote_cmd" | SSHPASS="$VPS_PASSWORD" sshpass -e ssh $SSH_OPTS "$host" "bash -s"
  else
    printf '%s\n' "$remote_cmd" | ssh $SSH_OPTS "$host" "bash -s"
  fi
}

rsync_run() {
  local host="$1"
  local target_dir="$2"

  local -a excludes=(
    --exclude ".git"
    --exclude "__pycache__"
    --exclude ".venv"
    --exclude "venv"
    --exclude "*.pyc"
    --exclude ".DS_Store"
    --exclude ".env"
    --exclude ".env.secrets"
    --exclude "*.log"
    --exclude "phoenixd-data"
    --exclude "phoenixd-test-data"
  )

  if [[ -n "${VPS_PASSWORD:-}" ]]; then
    need_cmd sshpass
    SSHPASS="$VPS_PASSWORD" sshpass -e rsync -az --delete "${excludes[@]}" -e "ssh $SSH_OPTS" ./ "$host:$target_dir/"
  else
    rsync -az --delete "${excludes[@]}" -e "ssh $SSH_OPTS" ./ "$host:$target_dir/"
  fi
}

deploy_local() {
  need_cmd python3

  if [[ ! -d "venv" ]]; then
    python3 -m venv venv
  fi

  ./venv/bin/pip install -r requirements.txt

  pkill -f "uvicorn server:app --host 127.0.0.1 --port $PORT" >/dev/null 2>&1 || true
  nohup ./venv/bin/uvicorn server:app --host 127.0.0.1 --port "$PORT" > local-app.log 2>&1 < /dev/null &
  echo $! > .local-uvicorn.pid
  sleep 1

  echo "Local deploy complete"
  echo "App: http://127.0.0.1:$PORT"
  echo "Log: $ROOT_DIR/local-app.log"
}

deploy_prod() {
  need_cmd rsync
  need_cmd ssh

  if [[ -z "${VPS_IP:-}" || -z "${VPS_USER:-}" ]]; then
    echo "VPS_IP and VPS_USER are required for prod deploy" >&2
    exit 1
  fi

  local host="$VPS_USER@$VPS_IP"

  echo "Syncing code to $host:$REMOTE_DIR"
  rsync_run "$host" "$REMOTE_DIR"

  local remote_cmd
remote_cmd=$(cat <<REMOTE
set -euo pipefail
cd "$REMOTE_DIR"
if [[ ! -d "venv" ]]; then
  python3 -m venv venv
fi
./venv/bin/pip install -r requirements.txt >/dev/null

if systemctl list-unit-files | grep -q '^alittlebitofmoney\\.service'; then
  systemctl restart alittlebitofmoney.service
  systemctl is-active --quiet alittlebitofmoney.service
  systemctl --no-pager --full status alittlebitofmoney.service | sed -n '1,20p'
else
  pkill -f "uvicorn server:app --host 127.0.0.1 --port $PORT" >/dev/null 2>&1 || true
  nohup ./venv/bin/uvicorn server:app --host 127.0.0.1 --port "$PORT" > app.log 2>&1 < /dev/null &
  echo \$! > .uvicorn.pid
  sleep 1
  PID=\$(cat .uvicorn.pid)
  ps -p "\$PID" -o pid= -o user= -o args=
fi

curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null
echo "Prod deploy complete"
REMOTE
)

  ssh_run "$host" "$remote_cmd"

  echo "Prod app expected on 127.0.0.1:$PORT (behind nginx)"
  echo "Version v0.2.0 | $(date +%Y) | alittlebitofmoney.com"
}

case "$MODE" in
  local)
    deploy_local
    ;;
  prod)
    deploy_prod
    ;;
  *)
    usage
    exit 1
    ;;
esac
