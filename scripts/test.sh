#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"

if [[ ! -f ".env" ]]; then
  echo "Missing .env file in current directory" >&2
  exit 1
fi

set -a
source ./.env
set +a

if [[ -z "${PHOENIX_TEST_PASSWORD:-}" ]]; then
  echo "PHOENIX_TEST_PASSWORD is missing from .env" >&2
  exit 1
fi

TEST_PHOENIX_URL="${PHOENIX_TEST_URL:-http://localhost:9741}"

echo "=== Step 1: Request API call (expect 402) ==="
STEP1_RAW=$(curl -sS -w "\n%{http_code}" -X POST "$BASE_URL/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello in 5 words"}],
    "max_tokens": 20
  }')

STEP1_BODY=$(echo "$STEP1_RAW" | sed '$d')
STEP1_CODE=$(echo "$STEP1_RAW" | tail -n1)
echo "$STEP1_BODY" | jq .

if [[ "$STEP1_CODE" != "402" ]]; then
  echo "Expected 402 on step 1, got $STEP1_CODE" >&2
  exit 1
fi

INVOICE=$(echo "$STEP1_BODY" | jq -r '.invoice // empty')
AMOUNT=$(echo "$STEP1_BODY" | jq -r '.amount_sats // empty')

if [[ -z "$INVOICE" || -z "$AMOUNT" ]]; then
  echo "Missing invoice/amount in step 1 response" >&2
  exit 1
fi

echo
echo "=== Step 2: Pay invoice ($AMOUNT sats) via test wallet on 9741 ==="
PAY_RESPONSE=$(curl -sS -X POST "$TEST_PHOENIX_URL/payinvoice" \
  -u ":$PHOENIX_TEST_PASSWORD" \
  --data-urlencode "invoice=$INVOICE")

echo "$PAY_RESPONSE" | jq .

PREIMAGE=$(echo "$PAY_RESPONSE" | jq -r '.paymentPreimage // empty')
if [[ -z "$PREIMAGE" ]]; then
  echo "Payment did not return a preimage" >&2
  exit 1
fi

echo
echo "=== Step 3: Redeem ==="
STEP3_RAW=$(curl -sS -w "\n%{http_code}" "$BASE_URL/redeem?preimage=$PREIMAGE")
STEP3_BODY=$(echo "$STEP3_RAW" | sed '$d')
STEP3_CODE=$(echo "$STEP3_RAW" | tail -n1)

echo "$STEP3_BODY" | jq .

if [[ "$STEP3_CODE" != "200" ]]; then
  echo "Expected 200 on redeem, got $STEP3_CODE" >&2
  exit 1
fi

echo
echo "=== Done: end-to-end payment + redeem succeeded ==="
