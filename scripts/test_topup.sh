#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"
TOPUP_AMOUNT="${TOPUP_AMOUNT:-120}"
REFILL_AMOUNT="${REFILL_AMOUNT:-180}"
TEST_PHOENIX_URL="${PHOENIX_TEST_URL:-http://localhost:9741}"

if [[ -f ".env.secrets" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env.secrets
  set +a
fi
if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

if [[ -z "${PHOENIX_TEST_PASSWORD:-}" ]]; then
  echo "PHOENIX_TEST_PASSWORD is missing from env/.env/.env.secrets" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for this script" >&2
  exit 1
fi

post_json() {
  local url="$1"
  local body="$2"
  curl -sS -w "\n%{http_code}" -X POST "$url" -H "Content-Type: application/json" -d "$body"
}

pay_invoice() {
  local invoice="$1"
  curl -sS -X POST "$TEST_PHOENIX_URL/payinvoice" \
    -u ":$PHOENIX_TEST_PASSWORD" \
    --data-urlencode "invoice=$invoice"
}

echo "=== Step 1: create topup invoice (${TOPUP_AMOUNT} sats) ==="
STEP1_RAW="$(post_json "$BASE_URL/api/v1/topup" "{\"amount_sats\":$TOPUP_AMOUNT}")"
STEP1_BODY="$(echo "$STEP1_RAW" | sed '$d')"
STEP1_CODE="$(echo "$STEP1_RAW" | tail -n1)"
echo "$STEP1_BODY" | jq .

if [[ "$STEP1_CODE" != "402" ]]; then
  echo "Expected 402 from /topup, got $STEP1_CODE" >&2
  exit 1
fi

INVOICE="$(echo "$STEP1_BODY" | jq -r '.invoice // empty')"
if [[ -z "$INVOICE" ]]; then
  echo "Missing invoice in /topup response" >&2
  exit 1
fi

echo
echo "=== Step 2: pay topup invoice with test wallet ==="
PAY1="$(pay_invoice "$INVOICE")"
echo "$PAY1" | jq .
PREIMAGE1="$(echo "$PAY1" | jq -r '.paymentPreimage // empty')"
if [[ -z "$PREIMAGE1" ]]; then
  echo "Missing paymentPreimage for first topup invoice" >&2
  exit 1
fi

echo
echo "=== Step 3: claim topup and get bearer token ==="
CLAIM1_RAW="$(post_json "$BASE_URL/api/v1/topup/claim" "{\"preimage\":\"$PREIMAGE1\"}")"
CLAIM1_BODY="$(echo "$CLAIM1_RAW" | sed '$d')"
CLAIM1_CODE="$(echo "$CLAIM1_RAW" | tail -n1)"
echo "$CLAIM1_BODY" | jq .

if [[ "$CLAIM1_CODE" != "200" ]]; then
  echo "Expected 200 from /topup/claim, got $CLAIM1_CODE" >&2
  exit 1
fi

TOKEN="$(echo "$CLAIM1_BODY" | jq -r '.token // empty')"
BALANCE1="$(echo "$CLAIM1_BODY" | jq -r '.balance_sats // empty')"
if [[ -z "$TOKEN" || -z "$BALANCE1" ]]; then
  echo "Missing token/balance_sats in claim response" >&2
  exit 1
fi

echo
echo "=== Step 4: verify bearer insufficient-balance guard ==="
EXPENSIVE_RAW="$(curl -sS -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "X-Token: $TOKEN" \
  -d '{"model":"o1-pro","messages":[{"role":"user","content":"Say hello"}]}')"
EXPENSIVE_BODY="$(echo "$EXPENSIVE_RAW" | sed '$d')"
EXPENSIVE_CODE="$(echo "$EXPENSIVE_RAW" | tail -n1)"
echo "$EXPENSIVE_BODY" | jq .

if [[ "$EXPENSIVE_CODE" != "402" ]]; then
  echo "Expected 402 insufficient balance, got $EXPENSIVE_CODE" >&2
  exit 1
fi
ERR_CODE="$(echo "$EXPENSIVE_BODY" | jq -r '.error.code // empty')"
if [[ "$ERR_CODE" != "insufficient_balance" ]]; then
  echo "Expected error.code=insufficient_balance, got '$ERR_CODE'" >&2
  exit 1
fi

echo
echo "=== Step 5: create refill invoice with Bearer token (${REFILL_AMOUNT} sats) ==="
REFILL_RAW="$(curl -sS -w "\n%{http_code}" -X POST "$BASE_URL/api/v1/topup" \
  -H "Content-Type: application/json" \
  -H "X-Token: $TOKEN" \
  -d "{\"amount_sats\":$REFILL_AMOUNT}")"
REFILL_BODY="$(echo "$REFILL_RAW" | sed '$d')"
REFILL_CODE="$(echo "$REFILL_RAW" | tail -n1)"
echo "$REFILL_BODY" | jq .

if [[ "$REFILL_CODE" != "402" ]]; then
  echo "Expected 402 from refill /topup, got $REFILL_CODE" >&2
  exit 1
fi

REFILL_INVOICE="$(echo "$REFILL_BODY" | jq -r '.invoice // empty')"
if [[ -z "$REFILL_INVOICE" ]]; then
  echo "Missing refill invoice" >&2
  exit 1
fi

echo
echo "=== Step 6: pay refill invoice and claim onto same token ==="
PAY2="$(pay_invoice "$REFILL_INVOICE")"
echo "$PAY2" | jq .
PREIMAGE2="$(echo "$PAY2" | jq -r '.paymentPreimage // empty')"
if [[ -z "$PREIMAGE2" ]]; then
  echo "Missing paymentPreimage for refill invoice" >&2
  exit 1
fi

CLAIM2_RAW="$(post_json "$BASE_URL/api/v1/topup/claim" "{\"preimage\":\"$PREIMAGE2\",\"token\":\"$TOKEN\"}")"
CLAIM2_BODY="$(echo "$CLAIM2_RAW" | sed '$d')"
CLAIM2_CODE="$(echo "$CLAIM2_RAW" | tail -n1)"
echo "$CLAIM2_BODY" | jq .

if [[ "$CLAIM2_CODE" != "200" ]]; then
  echo "Expected 200 from refill /topup/claim, got $CLAIM2_CODE" >&2
  exit 1
fi

BALANCE2="$(echo "$CLAIM2_BODY" | jq -r '.balance_sats // empty')"
if [[ -z "$BALANCE2" ]]; then
  echo "Missing balance_sats after refill claim" >&2
  exit 1
fi
if (( BALANCE2 <= BALANCE1 )); then
  echo "Expected balance to increase after refill claim ($BALANCE1 -> $BALANCE2)" >&2
  exit 1
fi

echo
echo "=== Done: topup flow works (new token + refill + bearer guard) ==="
