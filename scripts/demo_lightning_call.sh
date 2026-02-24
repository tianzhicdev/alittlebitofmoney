#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-https://alittlebitofmoney.com}"
REQUEST_BODY="${REQUEST_BODY:-{
  \"model\": \"gpt-4o-mini\",
  \"messages\": [{\"role\": \"user\", \"content\": \"Say hello in 5 words.\"}],
  \"max_tokens\": 24
}}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for this demo script" >&2
  exit 1
fi

echo "=== Step 1: Create API request and get invoice ==="
STEP1_HEADERS="$(mktemp)"
STEP1_RAW=$(curl -sS -D "$STEP1_HEADERS" -w "\n%{http_code}" -X POST "$BASE_URL/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$REQUEST_BODY")

STEP1_BODY=$(echo "$STEP1_RAW" | sed '$d')
STEP1_CODE=$(echo "$STEP1_RAW" | tail -n1)

echo "$STEP1_BODY" | jq .

if [[ "$STEP1_CODE" != "402" ]]; then
  echo "Expected 402, got $STEP1_CODE" >&2
  exit 1
fi

INVOICE=$(echo "$STEP1_BODY" | jq -r '.invoice // empty')
AMOUNT=$(echo "$STEP1_BODY" | jq -r '.amount_sats // empty')
WWW_AUTH=$(grep -i '^WWW-Authenticate:' "$STEP1_HEADERS" | head -n1 | sed -E 's/^[^:]+:[[:space:]]*//; s/\r$//')
MACAROON=$(echo "$WWW_AUTH" | sed -nE 's/^L402[[:space:]]+macaroon="([^"]+)".*/\1/p')
rm -f "$STEP1_HEADERS"

if [[ -z "$INVOICE" || -z "$AMOUNT" || -z "$MACAROON" ]]; then
  echo "Missing invoice/amount/macaroon in step 1 response" >&2
  exit 1
fi

echo
echo "=== Step 2: Pay this invoice in your Lightning wallet ==="
echo "Amount: $AMOUNT sats"
echo
echo "$INVOICE"
echo
read -r -p "Paste payment preimage: " PREIMAGE

if [[ -z "$PREIMAGE" ]]; then
  echo "Preimage is required" >&2
  exit 1
fi

echo
echo "=== Step 3: Re-send with L402 authorization ==="
REDEEM_RAW=$(curl -sS -w "\n%{http_code}" -X POST "$BASE_URL/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "Authorization: L402 ${MACAROON}:${PREIMAGE}" \
  -d "$REQUEST_BODY")
REDEEM_BODY=$(echo "$REDEEM_RAW" | sed '$d')
REDEEM_CODE=$(echo "$REDEEM_RAW" | tail -n1)

echo "$REDEEM_BODY" | jq .

if [[ "$REDEEM_CODE" != "200" ]]; then
  echo "Expected 200 on authorized request, got $REDEEM_CODE" >&2
  exit 1
fi

echo
echo "=== Done ==="
