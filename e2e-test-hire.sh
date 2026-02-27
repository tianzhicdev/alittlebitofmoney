#!/usr/bin/env bash
set -euo pipefail

# End-to-end test for AI for Hire lifecycle.
# Creates three topup tokens (buyer + worker1 + worker2), tests the full flow:
#   list tasks → create task → submit quote → update quote → accept → quote-scoped messages
#   → access control → deliver → confirm → verify balances.
# Intended runtime: ssh captain (VPS). Requires Bash 4+ and local Phoenix test wallet.

BASE_URL="${BASE_URL:-${1:-https://alittlebitofmoney.com}}"
BASE_URL="${BASE_URL%/}"
PHOENIX_TEST_URL="${PHOENIX_TEST_URL:-http://localhost:9741}"
VERBOSE="${VERBOSE:-0}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" >&2
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

if (( BASH_VERSINFO[0] < 4 )); then
  fail "This script requires Bash 4+ and should be run on ssh captain (VPS)."
fi

for cmd in curl jq; do
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
done

if [[ -z "${PHOENIX_TEST_PASSWORD:-}" ]]; then
  fail "PHOENIX_TEST_PASSWORD is missing. Set it in env or .env."
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

LAST_STATUS=""
LAST_BODY_FILE=""

run_http() {
  local label="$1"
  shift
  local req_id
  req_id="$(date +%s%N)"
  LAST_BODY_FILE="${TMP_DIR}/body_${req_id}.txt"
  LAST_STATUS="$(curl -sS -o "$LAST_BODY_FILE" -w "%{http_code}" "$@")"
  if [[ "$VERBOSE" == "1" ]]; then
    echo "----- ${label} -----" >&2
    echo "HTTP ${LAST_STATUS}" >&2
    echo "Body:" >&2
    sed 's/^/  /' "$LAST_BODY_FILE" >&2
  fi
}

post_json() {
  local url="$1"
  local payload="$2"
  run_http "POST ${url}" -X POST "$url" -H "Content-Type: application/json" --data "$payload"
}

post_json_auth() {
  local url="$1"
  local payload="$2"
  local token="$3"
  run_http "POST AUTH ${url}" -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "X-Token: ${token}" \
    --data "$payload"
}

patch_json_auth() {
  local url="$1"
  local payload="$2"
  local token="$3"
  run_http "PATCH AUTH ${url}" -X PATCH "$url" \
    -H "Content-Type: application/json" \
    -H "X-Token: ${token}" \
    --data "$payload"
}

get_auth() {
  local url="$1"
  local token="$2"
  run_http "GET AUTH ${url}" "$url" -H "X-Token: ${token}"
}

get_url() {
  local url="$1"
  run_http "GET ${url}" "$url"
}

assert_status() {
  local expected="$1"
  if [[ "$LAST_STATUS" != "$expected" ]]; then
    fail "[${2:-}] Expected HTTP ${expected}, got ${LAST_STATUS}. Body: $(cat "$LAST_BODY_FILE")"
  fi
}

json_field() {
  jq -er "$1" "$LAST_BODY_FILE" 2>/dev/null || true
}

pay_invoice() {
  local invoice="$1"
  local pay_file="${TMP_DIR}/pay_$(date +%s%N).json"
  local pay_code
  pay_code="$(curl -sS -o "$pay_file" -w "%{http_code}" -X POST "${PHOENIX_TEST_URL%/}/payinvoice" \
    -u ":${PHOENIX_TEST_PASSWORD}" \
    --data-urlencode "invoice=${invoice}")"
  if (( pay_code < 200 || pay_code >= 300 )); then
    fail "Pay invoice failed with HTTP ${pay_code}. Response: $(cat "$pay_file")"
  fi
  local preimage
  preimage="$(jq -er '.paymentPreimage // empty' "$pay_file" 2>/dev/null || true)"
  [[ -n "$preimage" ]] || fail "No paymentPreimage in response: $(cat "$pay_file")"
  printf '%s' "$preimage"
}

create_funded_token() {
  local label="$1"
  local amount_sats="$2"

  log "Creating funded token for ${label} (${amount_sats} sats)"

  # Step 1: Create topup invoice
  post_json "${BASE_URL}/api/v1/topup" "{\"amount_sats\":${amount_sats}}"
  assert_status "402" "${label} topup"
  local invoice
  invoice="$(json_field '.invoice')"
  [[ -n "$invoice" ]] || fail "Missing invoice in topup response"

  # Step 2: Pay invoice
  local preimage
  preimage="$(pay_invoice "$invoice")"

  # Step 3: Claim token
  post_json "${BASE_URL}/api/v1/topup/claim" "{\"preimage\":\"${preimage}\"}"
  assert_status "200" "${label} claim"
  local token
  token="$(json_field '.token')"
  [[ -n "$token" ]] || fail "Missing token in claim response"

  log "  ${label} token created, balance: $(json_field '.balance_sats') sats"
  printf '%s' "$token"
}

# ── Create funded tokens ──────────────────────────────────────────

BUYER_TOKEN="$(create_funded_token "buyer" 1000)"
WORKER_TOKEN="$(create_funded_token "worker1" 200)"
WORKER2_TOKEN="$(create_funded_token "worker2" 200)"

# ── Get initial balances ──────────────────────────────────────────

log "Checking buyer balance"
get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$BUYER_TOKEN"
assert_status "200" "buyer me"
BUYER_INITIAL="$(json_field '.balance_sats')"
log "  Buyer balance: ${BUYER_INITIAL} sats"

log "Checking worker1 balance"
get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$WORKER_TOKEN"
assert_status "200" "worker1 me"
WORKER_INITIAL="$(json_field '.balance_sats')"
log "  Worker1 balance: ${WORKER_INITIAL} sats"

log "Checking worker2 balance"
get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$WORKER2_TOKEN"
assert_status "200" "worker2 me"
WORKER2_INITIAL="$(json_field '.balance_sats')"
log "  Worker2 balance: ${WORKER2_INITIAL} sats"

# ── List tasks (should work without auth) ─────────────────────────

log "Listing tasks (no auth)"
get_url "${BASE_URL}/api/v1/ai-for-hire/tasks"
assert_status "200" "list tasks"

# ── Create task (buyer, costs 50 sats) ────────────────────────────

log "Creating task (buyer)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks" \
  '{"title":"E2E Test Task","description":"Automated e2e-test-hire task","budget_sats":500}' \
  "$BUYER_TOKEN"
assert_status "201" "create task"
TASK_ID="$(json_field '.id')"
[[ -n "$TASK_ID" ]] || fail "Missing task id"
log "  Task ID: ${TASK_ID}"

# ── Get task detail (no auth) ─────────────────────────────────────

log "Getting task detail"
get_url "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}"
assert_status "200" "get task"
TASK_STATUS="$(json_field '.status')"
[[ "$TASK_STATUS" == "open" ]] || fail "Expected task status=open, got ${TASK_STATUS}"

# ── Submit quotes (worker1 + worker2, costs 10 sats each) ────────

log "Submitting quote (worker1)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes" \
  '{"price_sats":400,"description":"E2E test quote from worker1"}' \
  "$WORKER_TOKEN"
assert_status "201" "create quote1"
QUOTE1_ID="$(json_field '.id')"
[[ -n "$QUOTE1_ID" ]] || fail "Missing quote1 id"
log "  Quote1 ID: ${QUOTE1_ID}"

log "Submitting quote (worker2)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes" \
  '{"price_sats":350,"description":"E2E test quote from worker2"}' \
  "$WORKER2_TOKEN"
assert_status "201" "create quote2"
QUOTE2_ID="$(json_field '.id')"
[[ -n "$QUOTE2_ID" ]] || fail "Missing quote2 id"
log "  Quote2 ID: ${QUOTE2_ID}"

# ── Update quote (worker1 lowers price) ──────────────────────────

log "Worker1 updates quote price to 300"
patch_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}" \
  '{"price_sats":300,"description":"Updated: will do it for 300"}' \
  "$WORKER_TOKEN"
assert_status "200" "update quote"
UPDATED_PRICE="$(json_field '.price_sats')"
[[ "$UPDATED_PRICE" == "300" ]] || fail "Expected updated price=300, got ${UPDATED_PRICE}"
log "  Quote1 price updated to ${UPDATED_PRICE} sats"

# ── Worker2 cannot update worker1's quote ─────────────────────────

log "Worker2 tries to update worker1's quote (should fail 403)"
patch_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}" \
  '{"price_sats":250}' \
  "$WORKER2_TOKEN"
assert_status "403" "outsider update quote"

# ── Buyer messages worker1 on their quote thread ─────────────────

log "Buyer sends message on quote1 thread"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}/messages" \
  '{"body":"Can you start today?"}' \
  "$BUYER_TOKEN"
assert_status "201" "buyer send message on quote1"

log "Worker1 reads messages on quote1 thread"
get_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}/messages" \
  "$WORKER_TOKEN"
assert_status "200" "worker1 get messages on quote1"
MSG_COUNT="$(jq '.messages | length' "$LAST_BODY_FILE")"
[[ "$MSG_COUNT" -ge 1 ]] || fail "Expected at least 1 message, got ${MSG_COUNT}"

# ── Buyer messages worker2 on their quote thread ─────────────────

log "Buyer sends message on quote2 thread"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE2_ID}/messages" \
  '{"body":"What is your timeline?"}' \
  "$BUYER_TOKEN"
assert_status "201" "buyer send message on quote2"

# ── Access control: worker1 cannot read worker2's thread ─────────

log "Worker1 tries to read quote2 messages (should fail 403)"
get_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE2_ID}/messages" \
  "$WORKER_TOKEN"
assert_status "403" "worker1 read quote2 messages"

log "Worker2 tries to read quote1 messages (should fail 403)"
get_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}/messages" \
  "$WORKER2_TOKEN"
assert_status "403" "worker2 read quote1 messages"

# ── Verify task detail shows message_count per quote ──────────────

log "Checking message_count per quote in task detail"
get_url "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}"
assert_status "200" "task detail with message_count"
Q1_MSG_COUNT="$(jq -r '.quotes[] | select(.id == "'"$QUOTE1_ID"'") | .message_count' "$LAST_BODY_FILE")"
Q2_MSG_COUNT="$(jq -r '.quotes[] | select(.id == "'"$QUOTE2_ID"'") | .message_count' "$LAST_BODY_FILE")"
[[ "$Q1_MSG_COUNT" -ge 1 ]] || fail "Expected quote1 message_count >= 1, got ${Q1_MSG_COUNT}"
[[ "$Q2_MSG_COUNT" -ge 1 ]] || fail "Expected quote2 message_count >= 1, got ${Q2_MSG_COUNT}"
log "  Quote1 messages: ${Q1_MSG_COUNT}, Quote2 messages: ${Q2_MSG_COUNT}"

# ── Accept quote1 (buyer, locks escrow) ──────────────────────────

log "Accepting quote1 (buyer)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE1_ID}/accept" \
  '{}' \
  "$BUYER_TOKEN"
assert_status "200" "accept quote"
ESCROWED="$(json_field '.escrowed_sats')"
log "  Escrowed: ${ESCROWED} sats"

# ── Verify task is in_escrow ──────────────────────────────────────

get_url "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}"
assert_status "200" "get task after accept"
TASK_STATUS="$(json_field '.status')"
[[ "$TASK_STATUS" == "in_escrow" ]] || fail "Expected status=in_escrow, got ${TASK_STATUS}"

# ── Worker2's quote should be rejected; cannot message on it ─────

log "Worker2 tries to message rejected quote (should fail 409)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/quotes/${QUOTE2_ID}/messages" \
  '{"body":"Am I still in?"}' \
  "$WORKER2_TOKEN"
assert_status "409" "worker2 message rejected quote"

# ── Deliver work (worker1) ──────────────────────────────────────

log "Delivering work (worker1)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/deliver" \
  '{"filename":"result.txt","content_base64":"RTJFIFRLC3QgZGVsaXZlcnk=","notes":"E2E delivery"}' \
  "$WORKER_TOKEN"
assert_status "201" "deliver"

# ── Verify task is delivered ──────────────────────────────────────

get_url "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}"
assert_status "200" "get task after deliver"
TASK_STATUS="$(json_field '.status')"
[[ "$TASK_STATUS" == "delivered" ]] || fail "Expected status=delivered, got ${TASK_STATUS}"

# ── Confirm delivery (buyer, releases escrow) ─────────────────────

log "Confirming delivery (buyer)"
post_json_auth "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}/confirm" \
  '{}' \
  "$BUYER_TOKEN"
assert_status "200" "confirm"
RELEASED="$(json_field '.released_sats')"
log "  Released: ${RELEASED} sats"

# ── Verify task is completed ──────────────────────────────────────

get_url "${BASE_URL}/api/v1/ai-for-hire/tasks/${TASK_ID}"
assert_status "200" "get task after confirm"
TASK_STATUS="$(json_field '.status')"
[[ "$TASK_STATUS" == "completed" ]] || fail "Expected status=completed, got ${TASK_STATUS}"

# ── Verify balances ──────────────────────────────────────────────

log "Verifying final balances"

get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$BUYER_TOKEN"
assert_status "200" "buyer final"
BUYER_FINAL="$(json_field '.balance_sats')"

get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$WORKER_TOKEN"
assert_status "200" "worker1 final"
WORKER_FINAL="$(json_field '.balance_sats')"

get_auth "${BASE_URL}/api/v1/ai-for-hire/me" "$WORKER2_TOKEN"
assert_status "200" "worker2 final"
WORKER2_FINAL="$(json_field '.balance_sats')"

# Buyer: started with 1000, spent 50 (task) + 300 (escrow) = 650 remaining
BUYER_EXPECTED=$((BUYER_INITIAL - 50 - 300))
if [[ "$BUYER_FINAL" -ne "$BUYER_EXPECTED" ]]; then
  fail "Buyer balance mismatch: expected ${BUYER_EXPECTED}, got ${BUYER_FINAL}"
fi
log "  Buyer: ${BUYER_INITIAL} → ${BUYER_FINAL} sats (spent 350)"

# Worker1: started with 200, spent 10 (quote) + received 300 (escrow) = 490
WORKER_EXPECTED=$((WORKER_INITIAL - 10 + 300))
if [[ "$WORKER_FINAL" -ne "$WORKER_EXPECTED" ]]; then
  fail "Worker1 balance mismatch: expected ${WORKER_EXPECTED}, got ${WORKER_FINAL}"
fi
log "  Worker1: ${WORKER_INITIAL} → ${WORKER_FINAL} sats (earned 290 net)"

# Worker2: started with 200, spent 10 (quote, rejected) = 190
WORKER2_EXPECTED=$((WORKER2_INITIAL - 10))
if [[ "$WORKER2_FINAL" -ne "$WORKER2_EXPECTED" ]]; then
  fail "Worker2 balance mismatch: expected ${WORKER2_EXPECTED}, got ${WORKER2_FINAL}"
fi
log "  Worker2: ${WORKER2_INITIAL} → ${WORKER2_FINAL} sats (spent 10, no earnings)"

log "All hire e2e tests passed!"
