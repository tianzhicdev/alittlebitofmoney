#!/usr/bin/env bash
set -euo pipefail

# End-to-end test for ALL configured API endpoints discovered from /api/catalog.
# Endpoint examples from config drive BOTH UI code snippets and this test script.
# Intended runtime: ssh captain (VPS). This script requires Bash 4+ (mapfile)
# and local access to the Phoenix test wallet at http://localhost:9741.

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

if (( BASH_VERSINFO[0] < 4 )); then
  fail "This script requires Bash 4+ and should be run on ssh captain (VPS)."
fi

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

E2E_TEXT_FILE="${TMP_DIR}/e2e-invalid.txt"
printf 'this is not a valid media payload for upstream APIs\n' > "$E2E_TEXT_FILE"

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

post_json_with_auth() {
  local url="$1"
  local payload="$2"
  local auth="$3"
  run_http "POST JSON AUTH ${url}" -X POST "$url" \
    -H "Content-Type: application/json" \
    -H "Authorization: ${auth}" \
    --data "$payload"
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

post_multipart_with_auth() {
  local url="$1"
  local auth="$2"
  shift 2

  local form_args=()
  while (($#)); do
    form_args+=(-F "$1")
    shift
  done

  run_http "POST MULTIPART AUTH ${url}" -X POST "$url" -H "Authorization: ${auth}" "${form_args[@]}"
}

resolve_file_placeholder() {
  local raw_path="$1"
  case "$raw_path" in
    "__E2E_TEXT_FILE__")
      printf '%s' "$E2E_TEXT_FILE"
      ;;
    *)
      printf '%s' "$raw_path"
      ;;
  esac
}

post_multipart_from_json_fields() {
  local url="$1"
  local fields_json="$2"

  local form_entries=()
  mapfile -t form_entries < <(jq -cr 'to_entries[]?' <<<"$fields_json")

  local form_args=()
  local entry
  for entry in "${form_entries[@]}"; do
    local key
    local value
    key="$(jq -r '.key' <<<"$entry")"
    value="$(jq -r '.value | tostring' <<<"$entry")"

    if [[ "$value" == @* ]]; then
      local file_ref file_path
      file_ref="${value#@}"
      file_path="$(resolve_file_placeholder "$file_ref")"
      [[ -f "$file_path" ]] || fail "Multipart file does not exist: ${file_path}"
      form_args+=("${key}=@${file_path}")
    else
      form_args+=("${key}=${value}")
    fi
  done

  post_multipart "$url" "${form_args[@]}"
}

post_multipart_from_json_fields_with_auth() {
  local url="$1"
  local fields_json="$2"
  local auth="$3"

  local form_entries=()
  mapfile -t form_entries < <(jq -cr 'to_entries[]?' <<<"$fields_json")

  local form_args=()
  local entry
  for entry in "${form_entries[@]}"; do
    local key
    local value
    key="$(jq -r '.key' <<<"$entry")"
    value="$(jq -r '.value | tostring' <<<"$entry")"

    if [[ "$value" == @* ]]; then
      local file_ref file_path
      file_ref="${value#@}"
      file_path="$(resolve_file_placeholder "$file_ref")"
      [[ -f "$file_path" ]] || fail "Multipart file does not exist: ${file_path}"
      form_args+=("${key}=@${file_path}")
    else
      form_args+=("${key}=${value}")
    fi
  done

  post_multipart_with_auth "$url" "$auth" "${form_args[@]}"
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

assert_authorized_status() {
  local expected="$1"
  if [[ "$expected" == "4xx" ]]; then
    assert_status_4xx
    return
  fi
  assert_status "$expected"
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

macaroon_from_www_auth() {
  local www_auth="$1"
  local value
  value="$(sed -nE 's/^L402[[:space:]]+macaroon="([^"]+)".*/\1/p' <<<"$www_auth")"
  printf '%s' "$value"
}

invoice_from_www_auth() {
  local www_auth="$1"
  local value
  value="$(sed -nE 's/.*invoice="([^"]+)".*/\1/p' <<<"$www_auth")"
  printf '%s' "$value"
}

extract_error_message() {
  local msg
  msg="$(jq -er '.error.message // .error // empty' "$LAST_BODY_FILE" 2>/dev/null || true)"
  if [[ -n "$msg" ]]; then
    printf '%s' "$msg"
    return
  fi
  tr '\n' ' ' < "$LAST_BODY_FILE"
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

log "Fetching API catalog from ${CATALOG_URL}"
CATALOG_FILE="${TMP_DIR}/catalog.json"
curl -sS "${CATALOG_URL}" > "$CATALOG_FILE"
jq -e . "$CATALOG_FILE" >/dev/null || fail "Catalog response is not valid JSON"

mapfile -t ENDPOINT_META < <(
  jq -cr '
    [
      .apis
      | to_entries[] as $api
      | ($api.value.endpoints // [])[]
      | {
          api_name: $api.key,
          method: (.method // "POST" | ascii_upcase),
          path: (.path // ""),
          example: (.example // null)
        }
    ]
    | sort_by(.api_name, .path, .method)
    | .[]
  ' "$CATALOG_FILE"
)

[[ "${#ENDPOINT_META[@]}" -gt 0 ]] || fail "No endpoints found in catalog"
log "Catalog contains ${#ENDPOINT_META[@]} endpoint(s)"

FIRST_JSON_URL=""
FIRST_JSON_BODY="{}"
meta=""
for meta in "${ENDPOINT_META[@]}"; do
  method="$(jq -r '.method' <<<"$meta")"
  content_type="$(jq -r '.example.content_type // empty' <<<"$meta")"
  if [[ "$method" == "POST" && "$content_type" == "json" ]]; then
    api_name="$(jq -r '.api_name' <<<"$meta")"
    endpoint_path="$(jq -r '.path' <<<"$meta")"
    FIRST_JSON_URL="${BASE_URL}/${api_name}${endpoint_path}"
    FIRST_JSON_BODY="$(jq -c '.example.body // {}' <<<"$meta")"
    break
  fi
done

log "Running shared proxy validation checks"

post_json "${BASE_URL}/openai/v1/not-a-real-endpoint" '{"x":1}'
assert_status "404"
assert_error_code "api_not_found"

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

if [[ -n "$FIRST_JSON_URL" ]]; then
  post_json_with_auth "$FIRST_JSON_URL" "$FIRST_JSON_BODY" "L402 invalid"
  assert_status "401"
  assert_error_code "invalid_l402"
fi

tested_count=0

for meta in "${ENDPOINT_META[@]}"; do
  api_name="$(jq -r '.api_name' <<<"$meta")"
  method="$(jq -r '.method' <<<"$meta")"
  endpoint_path="$(jq -r '.path' <<<"$meta")"
  content_type="$(jq -r '.example.content_type // empty' <<<"$meta")"

  [[ "$method" == "POST" ]] || fail "Unsupported endpoint method in catalog: ${api_name} ${method} ${endpoint_path}"
  [[ -n "$content_type" ]] || fail "Endpoint ${api_name}${endpoint_path} is missing example.content_type in catalog"

  endpoint_url="${BASE_URL}/${api_name}${endpoint_path}"
  tested_count=$((tested_count + 1))
  log "Testing ${api_name} ${endpoint_path} (${tested_count}/${#ENDPOINT_META[@]})"

  if [[ "$content_type" == "json" ]]; then
    required_field="$(jq -r '.example.e2e.required_field // empty' <<<"$meta")"
    if [[ -n "$required_field" ]]; then
      missing_body="$(jq -c --arg field "$required_field" '.example.body // {} | del(.[$field])' <<<"$meta")"
      post_json "$endpoint_url" "$missing_body"
      assert_status "400"
      assert_error_code "missing_required_field"
    fi

    invoice_request_body="$(jq -c '.example.e2e.invalid_body // .example.body // {}' <<<"$meta")"
    post_json "$endpoint_url" "$invoice_request_body"
  elif [[ "$content_type" == "multipart" ]]; then
    invoice_request_fields="$(jq -c '.example.e2e.invalid_fields // .example.fields // {}' <<<"$meta")"
    post_multipart_from_json_fields "$endpoint_url" "$invoice_request_fields"
  else
    fail "Unsupported example.content_type '${content_type}' for ${api_name}${endpoint_path}"
  fi

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
  www_auth="$(header_value 'WWW-Authenticate')"
  macaroon="$(macaroon_from_www_auth "$www_auth")"
  challenge_invoice="$(invoice_from_www_auth "$www_auth")"

  [[ -n "$header_invoice" ]] || fail "Missing X-Lightning-Invoice header"
  [[ -n "$header_hash" ]] || fail "Missing X-Payment-Hash header"
  [[ -n "$header_price" ]] || fail "Missing X-Price-Sats header"
  [[ -n "$www_auth" ]] || fail "Missing WWW-Authenticate header"
  [[ -n "$macaroon" ]] || fail "Missing macaroon in WWW-Authenticate header"
  [[ -n "$challenge_invoice" ]] || fail "Missing invoice in WWW-Authenticate header"
  [[ "$header_invoice" == "$invoice" ]] || fail "X-Lightning-Invoice header mismatch"
  [[ "$header_hash" == "$payment_hash" ]] || fail "X-Payment-Hash header mismatch"
  [[ "$header_price" == "$amount_sats" ]] || fail "X-Price-Sats header mismatch"
  [[ "$challenge_invoice" == "$invoice" ]] || fail "WWW-Authenticate invoice mismatch"

  preimage="$(pay_invoice "$invoice")"
  l402_auth="L402 ${macaroon}:${preimage}"

  if [[ "$content_type" == "json" ]]; then
    post_json_with_auth "$endpoint_url" "$invoice_request_body" "$l402_auth"
  else
    post_multipart_from_json_fields_with_auth "$endpoint_url" "$invoice_request_fields" "$l402_auth"
  fi
  expected_authorized_status="$(jq -r '.example.e2e.authorized_status // .example.e2e.redeem_status // "4xx"' <<<"$meta")"
  assert_authorized_status "$expected_authorized_status"

  if [[ "$expected_authorized_status" == "4xx" ]]; then
    upstream_message="$(extract_error_message)"
    require_error_message="$(jq -r 'if (.example.e2e | has("require_error_message")) then (.example.e2e.require_error_message | tostring) else "true" end' <<<"$meta")"
    if [[ "$require_error_message" == "true" ]]; then
      [[ -n "$upstream_message" ]] || fail "Missing forwarded error message after authorized request"
    fi

    expected_keyword="$(jq -r '.example.e2e.error_keyword // empty' <<<"$meta")"
    if [[ -n "$expected_keyword" && "$STRICT_KEYWORD_MATCH" == "1" ]]; then
      if ! echo "$upstream_message" | grep -qi "$expected_keyword"; then
        fail "Forwarded message for ${endpoint_path} did not mention '${expected_keyword}'. Message: ${upstream_message}"
      fi
    fi
  fi

  if [[ "$content_type" == "json" ]]; then
    post_json_with_auth "$endpoint_url" "$invoice_request_body" "$l402_auth"
  else
    post_multipart_from_json_fields_with_auth "$endpoint_url" "$invoice_request_fields" "$l402_auth"
  fi
  assert_status "400"
  assert_error_code "payment_already_used"
done

log "All tests passed for ${tested_count} endpoint(s)"
