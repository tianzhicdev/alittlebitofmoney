#!/usr/bin/env bash
set -euo pipefail

# End-to-end test for ALL configured API endpoints discovered from /api/catalog.
# This script is intended to run on the captain/VPS host where phoenixd-test is reachable.

BASE_URL="${BASE_URL:-${1:-https://alittlebitofmoney.com}}"
BASE_URL="${BASE_URL%/}"
CATALOG_URL="${CATALOG_URL:-${BASE_URL}/api/catalog}"
PHOENIX_TEST_URL="${PHOENIX_TEST_URL:-http://localhost:9741}"
STRICT_KEYWORD_MATCH="${STRICT_KEYWORD_MATCH:-1}"
VERBOSE="${VERBOSE:-0}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

for cmd in curl jq mktemp tr sed grep head; do
  require_cmd "$cmd"
done

if [[ -z "${PHOENIX_TEST_PASSWORD:-}" ]]; then
  fail "PHOENIX_TEST_PASSWORD is missing. Set it in env or .env."
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

LAST_STATUS=""
LAST_BODY_FILE=""
LAST_HEADERS_FILE=""
LAST_REQUEST_LABEL=""

run_http() {
  local label="$1"
  shift
  local req_id
  req_id="$(date +%s%N)"
  LAST_BODY_FILE="${TMP_DIR}/body_${req_id}.txt"
  LAST_HEADERS_FILE="${TMP_DIR}/headers_${req_id}.txt"
  LAST_REQUEST_LABEL="$label"

  LAST_STATUS="$(curl -sS -o "$LAST_BODY_FILE" -D "$LAST_HEADERS_FILE" -w "%{http_code}" "$@")"

  if [[ "$VERBOSE" == "1" ]]; then
    echo "----- ${LAST_REQUEST_LABEL} -----"
    echo "HTTP ${LAST_STATUS}"
    echo "Headers:"
    sed 's/^/  /' "$LAST_HEADERS_FILE"
    echo "Body:"
    sed 's/^/  /' "$LAST_BODY_FILE"
  fi
}

post_json() {
  local url="$1"
  local payload="$2"
  run_http "POST JSON ${url}" -X POST "$url" -H "Content-Type: application/json" --data "$payload"
}

post_json_file() {
  local url="$1"
  local payload_file="$2"
  run_http "POST JSON FILE ${url}" -X POST "$url" -H "Content-Type: application/json" --data-binary "@${payload_file}"
}

post_text_plain() {
  local url="$1"
  local text_payload="$2"
  run_http "POST TEXT ${url}" -X POST "$url" -H "Content-Type: text/plain" --data "$text_payload"
}

post_multipart() {
  local url="$1"
  shift
  local form_args=()
  while (($#)); do
    form_args+=(-F "$1")
    shift
  done
  run_http "POST MULTIPART ${url}" -X POST "$url" "${form_args[@]}"
}

redeem_with_preimage() {
  local preimage="$1"
  run_http "GET REDEEM ${BASE_URL}/redeem?preimage=${preimage}" -G "${BASE_URL}/redeem" --data-urlencode "preimage=${preimage}"
}

assert_status() {
  local expected="$1"
  if [[ "$LAST_STATUS" != "$expected" ]]; then
    fail "Expected HTTP ${expected}, got ${LAST_STATUS}. Body: $(cat "$LAST_BODY_FILE")"
  fi
}

assert_status_4xx() {
  if (( LAST_STATUS < 400 || LAST_STATUS >= 500 )); then
    fail "Expected HTTP 4xx, got ${LAST_STATUS}. Body: $(cat "$LAST_BODY_FILE")"
  fi
}

json_required() {
  local expr="$1"
  local value
  value="$(jq -er "$expr" "$LAST_BODY_FILE" 2>/dev/null || true)"
  if [[ -z "$value" || "$value" == "null" ]]; then
    return 1
  fi
  printf '%s' "$value"
}

assert_error_code() {
  local expected="$1"
  local got
  got="$(json_required '.error.code // empty' || true)"
  [[ -n "$got" ]] || fail "Missing error.code. Body: $(cat "$LAST_BODY_FILE")"
  [[ "$got" == "$expected" ]] || fail "Expected error.code=${expected}, got ${got}. Body: $(cat "$LAST_BODY_FILE")"
}

header_value() {
  local header_name="$1"
  local value
  value="$(grep -i "^${header_name}:" "$LAST_HEADERS_FILE" | head -n1 | sed -E 's/^[^:]+:[[:space:]]*//' | tr -d '\r' || true)"
  printf '%s' "$value"
}

pay_invoice() {
  local invoice="$1"
  local pay_body_file="${TMP_DIR}/pay_$(date +%s%N).json"
  local pay_code

  pay_code="$(curl -sS -o "$pay_body_file" -w "%{http_code}" -X POST "${PHOENIX_TEST_URL%/}/payinvoice" \
    -u ":${PHOENIX_TEST_PASSWORD}" \
    --data-urlencode "invoice=${invoice}")"

  if (( pay_code < 200 || pay_code >= 300 )); then
    fail "Pay invoice failed with HTTP ${pay_code}. Response: $(cat "$pay_body_file")"
  fi

  if [[ "$VERBOSE" == "1" ]]; then
    {
      echo "----- POST PAYINVOICE ${PHOENIX_TEST_URL%/}/payinvoice -----"
      echo "HTTP ${pay_code}"
      echo "Body:"
      sed 's/^/  /' "$pay_body_file"
    } >&2
  fi

  local preimage
  preimage="$(jq -er '.paymentPreimage // empty' "$pay_body_file" 2>/dev/null || true)"
  [[ -n "$preimage" ]] || fail "Pay invoice returned no paymentPreimage. Response: $(cat "$pay_body_file")"
  if [[ "$VERBOSE" == "1" ]]; then
    echo "Preimage: ${preimage}" >&2
  fi
  printf '%s' "$preimage"
}

requires_json_path() {
  local endpoint_path="$1"
  case "$endpoint_path" in
    "/v1/chat/completions"|"/v1/images/generations"|"/v1/audio/speech"|"/v1/embeddings")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

expected_error_keyword_for_path() {
  local endpoint_path="$1"
  case "$endpoint_path" in
    "/v1/chat/completions")
      echo "messages"
      ;;
    "/v1/images/generations")
      echo "prompt"
      ;;
    "/v1/audio/speech")
      echo "input"
      ;;
    "/v1/audio/transcriptions")
      echo "file"
      ;;
    "/v1/embeddings")
      echo "input"
      ;;
    *)
      echo ""
      ;;
  esac
}

send_upstream_invalid_request() {
  local endpoint_url="$1"
  local endpoint_path="$2"
  local model_hint="$3"

  case "$endpoint_path" in
    "/v1/chat/completions"|"/v1/images/generations"|"/v1/audio/speech"|"/v1/embeddings")
      [[ -n "$model_hint" ]] || fail "No model hint available for ${endpoint_path}"
      post_json "$endpoint_url" "$(jq -cn --arg model "$model_hint" '{model:$model}')"
      ;;
    "/v1/audio/transcriptions")
      post_multipart "$endpoint_url" "model=whisper-1"
      ;;
    *)
      fail "No upstream-invalid request template for endpoint path ${endpoint_path}"
      ;;
  esac
}

log "Fetching API catalog from ${CATALOG_URL}"
CATALOG_FILE="${TMP_DIR}/catalog.json"
curl -sS "${CATALOG_URL}" > "$CATALOG_FILE"
jq -e . "$CATALOG_FILE" >/dev/null || fail "Catalog response is not valid JSON"

mapfile -t ENDPOINT_ROWS < <(
  jq -r '
    .apis
    | to_entries[]
    | .key as $api_name
    | .value.endpoints[]
    | [
        $api_name,
        (.method // "POST" | ascii_upcase),
        .path,
        (.price_type // ""),
        (
          if .models then
            (.models | keys | map(select(. != "_default")) | .[0] // "_default")
          else
            ""
          end
        )
      ]
    | @tsv
  ' "$CATALOG_FILE" | sort
)

[[ "${#ENDPOINT_ROWS[@]}" -gt 0 ]] || fail "No endpoints found in catalog"
log "Catalog contains ${#ENDPOINT_ROWS[@]} endpoint(s)"

FIRST_JSON_URL=""
for row in "${ENDPOINT_ROWS[@]}"; do
  IFS=$'\t' read -r api_name method endpoint_path price_type model_hint <<<"$row"
  if [[ "$method" != "POST" ]]; then
    continue
  fi
  if requires_json_path "$endpoint_path"; then
    FIRST_JSON_URL="${BASE_URL}/${api_name}${endpoint_path}"
    break
  fi
done

log "Running shared proxy validation checks"

post_json "${BASE_URL}/openai/v1/not-a-real-endpoint" '{"x":1}'
assert_status "404"
assert_error_code "api_not_found"

run_http "GET ${BASE_URL}/redeem" "${BASE_URL}/redeem"
assert_status "400"
assert_error_code "invalid_payment"

redeem_with_preimage "deadbeef"
assert_status "400"
assert_error_code "invalid_payment"

if [[ -n "$FIRST_JSON_URL" ]]; then
  post_text_plain "$FIRST_JSON_URL" 'this is not json'
  assert_status "400"
  assert_error_code "invalid_request"

  BIG_JSON_FILE="${TMP_DIR}/too_large.json"
  {
    printf '{"pad":"'
    head -c 120000 < /dev/zero | tr '\0' 'a'
    printf '"}'
  } > "$BIG_JSON_FILE"
  post_json_file "$FIRST_JSON_URL" "$BIG_JSON_FILE"
  assert_status "413"
  assert_error_code "request_too_large"
fi

tested_count=0

for row in "${ENDPOINT_ROWS[@]}"; do
  IFS=$'\t' read -r api_name method endpoint_path price_type model_hint <<<"$row"

  [[ "$method" == "POST" ]] || fail "Unsupported endpoint method in catalog: ${api_name} ${method} ${endpoint_path}"

  endpoint_url="${BASE_URL}/${api_name}${endpoint_path}"
  tested_count=$((tested_count + 1))
  log "Testing ${api_name} ${endpoint_path} (${tested_count}/${#ENDPOINT_ROWS[@]})"

  if requires_json_path "$endpoint_path"; then
    post_text_plain "$endpoint_url" 'not-json'
    assert_status "400"
    assert_error_code "invalid_request"
  fi

  send_upstream_invalid_request "$endpoint_url" "$endpoint_path" "$model_hint"
  assert_status "402"

  response_status="$(json_required '.status // empty' || true)"
  [[ "$response_status" == "payment_required" ]] || fail "Expected status=payment_required, got ${response_status}"

  invoice="$(json_required '.invoice // empty' || true)"
  payment_hash="$(json_required '.payment_hash // empty' || true)"
  amount_sats="$(json_required '.amount_sats // empty' || true)"
  expires_in="$(json_required '.expires_in // empty' || true)"

  [[ -n "$invoice" ]] || fail "Missing invoice in 402 response"
  [[ -n "$payment_hash" ]] || fail "Missing payment_hash in 402 response"
  [[ "$amount_sats" =~ ^[0-9]+$ ]] || fail "Invalid amount_sats in 402 response: ${amount_sats}"
  [[ "$expires_in" =~ ^[0-9]+$ ]] || fail "Invalid expires_in in 402 response: ${expires_in}"

  header_invoice="$(header_value 'X-Lightning-Invoice')"
  header_hash="$(header_value 'X-Payment-Hash')"
  header_price="$(header_value 'X-Price-Sats')"

  [[ -n "$header_invoice" ]] || fail "Missing X-Lightning-Invoice header"
  [[ -n "$header_hash" ]] || fail "Missing X-Payment-Hash header"
  [[ -n "$header_price" ]] || fail "Missing X-Price-Sats header"
  [[ "$header_invoice" == "$invoice" ]] || fail "X-Lightning-Invoice header mismatch"
  [[ "$header_hash" == "$payment_hash" ]] || fail "X-Payment-Hash header mismatch"
  [[ "$header_price" == "$amount_sats" ]] || fail "X-Price-Sats header mismatch"

  preimage="$(pay_invoice "$invoice")"

  redeem_with_preimage "$preimage"
  assert_status_4xx

  upstream_message="$(json_required '.error.message // empty' || true)"
  [[ -n "$upstream_message" ]] || fail "Missing forwarded error.message after redeem"

  expected_keyword="$(expected_error_keyword_for_path "$endpoint_path")"
  if [[ -n "$expected_keyword" && "$STRICT_KEYWORD_MATCH" == "1" ]]; then
    if ! echo "$upstream_message" | grep -qi "$expected_keyword"; then
      fail "Forwarded message for ${endpoint_path} did not mention '${expected_keyword}'. Message: ${upstream_message}"
    fi
  fi

  redeem_with_preimage "$preimage"
  assert_status "400"
  assert_error_code "payment_already_used"
done

log "All tests passed for ${tested_count} endpoint(s)"
