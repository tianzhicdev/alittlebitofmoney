from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
import uuid as _uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pymacaroons import Macaroon, Verifier

from lib.hire_store import (
    HireError,
    HireForbidden,
    HireInsufficientBalance,
    HireInvalidState,
    HireNotFound,
    HireStore,
)
from lib.phoenix import PhoenixClient, PhoenixError
from lib.topup_store import (
    SupabaseTopupStore,
    TopupInsufficientBalance,
    TopupInvalidPayment,
    TopupInvalidToken,
    TopupInvoiceAlreadyClaimed,
    TopupMissingToken,
)
from lib.used_hashes import UsedHashSet


# ── Daily rate limiter (promo loss protection) ────────────────────
# Tiered daily call caps per endpoint path. Resets at midnight UTC.
# In-memory only — restarts reset counters (fine for promo).
DAILY_RATE_LIMITS: Dict[str, int] = {
    # Expensive: video gen, pro reasoning models
    "/v1/video/generations": 10,
    # Medium: image gen/edit/variations
    "/v1/images/generations": 200,
    "/v1/images/edits": 200,
    "/v1/images/variations": 200,
    # Cheap: everything else gets 1000
    "_default": 1000,
}

_daily_counters: Dict[str, int] = {}
_daily_counters_date: str = ""


def _check_daily_limit(normalized_path: str) -> Optional[str]:
    """Return error message if daily limit exceeded, else None."""
    global _daily_counters, _daily_counters_date
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if today != _daily_counters_date:
        _daily_counters = {}
        _daily_counters_date = today

    limit = DAILY_RATE_LIMITS.get(normalized_path, DAILY_RATE_LIMITS["_default"])
    count = _daily_counters.get(normalized_path, 0)
    if count >= limit:
        return f"Daily limit of {limit} calls reached for {normalized_path}. Resets at midnight UTC."
    _daily_counters[normalized_path] = count + 1
    return None


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST_DIR / "index.html"
SATRING_VERIFY_PATH = BASE_DIR / ".well-known" / "satring-verify"

load_dotenv(BASE_DIR / ".env.secrets")
load_dotenv(BASE_DIR / ".env")

with CONFIG_PATH.open("r", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)


def _build_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


def _canonical_hash(payment_hash: str) -> str:
    return payment_hash.strip().lower()


def _hash_from_preimage(preimage: str) -> str:
    preimage = preimage.strip()
    if not preimage:
        raise ValueError("Missing preimage")

    try:
        raw = bytes.fromhex(preimage)
    except ValueError as exc:
        raise ValueError("Preimage must be hex-encoded") from exc

    if len(raw) != 32:
        raise ValueError("Preimage must decode to 32 bytes")

    return hashlib.sha256(raw).hexdigest()


def _resolve_api_endpoint(
    api_name: str, endpoint_path: str, method: str
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    api_config = CONFIG.get("apis", {}).get(api_name)
    raw_path = "/" + endpoint_path.lstrip("/")
    candidates = {
        raw_path.rstrip("/"),
        f"/v1/{endpoint_path.lstrip('/')}".rstrip("/"),
    }
    normalized_method = method.upper()
    if api_config is None:
        return None, None, raw_path

    for endpoint in api_config.get("endpoints", []):
        if endpoint.get("method", "POST").upper() != normalized_method:
            continue
        configured_path = endpoint.get("path", "").rstrip("/")
        if configured_path in candidates:
            return api_config, endpoint, configured_path

    return api_config, None, raw_path


def _utc_timestamp_iso(timestamp: float) -> Optional[str]:
    if timestamp <= 0:
        return None
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _frontend_missing_response() -> JSONResponse:
    return _build_error(
        503,
        "frontend_unavailable",
        "Frontend build not found. Run `cd frontend && npm run build`.",
    )


def _frontend_index_response() -> Response:
    if not FRONTEND_INDEX.exists():
        return _frontend_missing_response()
    return FileResponse(FRONTEND_INDEX)


def _resolve_frontend_file(path: str) -> Optional[Path]:
    if not path:
        return FRONTEND_INDEX if FRONTEND_INDEX.exists() else None

    requested_path = Path(path)
    if requested_path.is_absolute() or ".." in requested_path.parts:
        return None

    candidate = (FRONTEND_DIST_DIR / requested_path).resolve()
    dist_root = FRONTEND_DIST_DIR.resolve()
    if dist_root not in candidate.parents and candidate != dist_root:
        return None
    if candidate.is_file():
        return candidate
    return None


def _max_request_bytes(endpoint: Dict[str, Any]) -> int:
    endpoint_cap = endpoint.get("max_request_bytes")
    if endpoint_cap is not None:
        return int(endpoint_cap)
    return int(CONFIG.get("max_request_bytes", 32768))


def _resolve_model_config(
    endpoint: Dict[str, Any], model_name: str
) -> Optional[Dict[str, Any]]:
    models = endpoint.get("models", {})
    model_entry = models.get(model_name)
    if model_entry is None:
        model_entry = models.get("_default")
    if model_entry is None:
        return None
    if isinstance(model_entry, dict):
        return model_entry
    return {"price_sats": model_entry}


def _price_for_request(endpoint: Dict[str, Any], request_body: Dict[str, Any]) -> int:
    price_type = endpoint.get("price_type")
    if price_type == "flat":
        return int(endpoint.get("price_sats", 0))
    if price_type == "per_model":
        requested_model = request_body.get("model")
        model_name = str(requested_model) if requested_model is not None else "_default"
        model_config = _resolve_model_config(endpoint, model_name)
        if model_config is None:
            raise LookupError(f"model_not_supported:{model_name}")
        return int(model_config.get("price_sats", 0))
    raise ValueError(f"unsupported price type: {price_type}")


def _apply_output_token_cap(
    endpoint: Dict[str, Any],
    body: Dict[str, Any],
) -> Dict[str, Any]:
    """Enforce max_output_tokens cap from model config on a request body."""
    requested_model = body.get("model")
    model_name = str(requested_model) if requested_model is not None else "_default"
    model_config = _resolve_model_config(endpoint, model_name)
    if model_config is None:
        raise LookupError(f"model_not_supported:{model_name}")

    cap = model_config.get("max_output_tokens")
    if cap is not None:
        cap_int = int(cap)
        requested_max = body.get("max_tokens")
        if requested_max is None:
            requested_max = body.get("max_completion_tokens")
        if requested_max is None:
            requested_max = body.get("max_output_tokens")
        try:
            requested_max_int = int(requested_max) if requested_max is not None else None
        except (TypeError, ValueError):
            requested_max_int = None

        if requested_max_int is None or requested_max_int > cap_int:
            body["max_output_tokens"] = cap_int
        else:
            body["max_output_tokens"] = requested_max_int
    body.pop("max_completion_tokens", None)
    body.pop("max_tokens", None)
    return body


def _apply_request_rules(
    endpoint_path: str,
    endpoint: Dict[str, Any],
    request_body: Dict[str, Any],
) -> Dict[str, Any]:
    body = dict(request_body)

    if endpoint_path == "/v1/chat/completions":
        body = _apply_output_token_cap(endpoint, body)
        # Restore max_tokens key for chat completions API compatibility
        cap_val = body.pop("max_output_tokens", None)
        if cap_val is not None:
            body["max_tokens"] = cap_val

    if endpoint_path == "/v1/responses":
        body = _apply_output_token_cap(endpoint, body)

    if endpoint_path in {"/v1/images/generations", "/v1/images/edits"}:
        body["n"] = 1

    if endpoint_path == "/v1/video/generations":
        body["n"] = 1

    return body


_REQUIRED_FIELDS: Dict[str, list[tuple[str, Any]]] = {
    "/v1/chat/completions": [("messages", list)],
    "/v1/responses": [("input", (str, list))],
    "/v1/images/generations": [("prompt", str)],
    "/v1/audio/speech": [("input", str), ("voice", str)],
    "/v1/embeddings": [("input", (str, list))],
    "/v1/moderations": [("input", (str, list))],
    "/v1/video/generations": [("prompt", str)],
}


def _expected_type_label(expected_type: Any) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(t.__name__ for t in expected_type)
    if isinstance(expected_type, type):
        return expected_type.__name__
    return "valid type"


def _validate_required_fields(
    normalized_path: str,
    request_body: Dict[str, Any],
) -> Optional[JSONResponse]:
    """
    Validate required JSON fields before issuing an invoice.

    Multipart endpoints (audio/transcriptions, audio/translations, images/edits,
    images/variations) are intentionally not pre-validated here because the
    request body is stored as raw multipart bytes, not parsed into JSON.
    """
    requirements = _REQUIRED_FIELDS.get(normalized_path)
    if not requirements:
        return None

    for field_name, expected_type in requirements:
        value = request_body.get(field_name)
        if value is None:
            return _build_error(
                400,
                "missing_required_field",
                f"Required field '{field_name}' is missing",
            )

        if not isinstance(value, expected_type):
            return _build_error(
                400,
                "invalid_field_type",
                f"Field '{field_name}' must be {_expected_type_label(expected_type)}",
            )

        if isinstance(value, list) and len(value) == 0:
            return _build_error(
                400,
                "invalid_field_value",
                f"Field '{field_name}' must not be empty",
            )

        if isinstance(value, str) and not value.strip():
            return _build_error(
                400,
                "invalid_field_value",
                f"Field '{field_name}' must not be empty",
            )

    return None


def _sats_to_usd_cents(sats: int, btc_usd: Optional[float]) -> Optional[float]:
    if btc_usd is None:
        return None
    cents = (
        Decimal(sats)
        * Decimal(str(btc_usd))
        / Decimal("100000000")
        * Decimal("100")
    )
    return float(cents.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _build_catalog(
    btc_usd: Optional[float],
    btc_usd_updated_at: Optional[str],
) -> Dict[str, Any]:
    apis: Dict[str, Any] = {}
    for api_name, api_config in CONFIG.get("apis", {}).items():
        endpoints = []
        for endpoint in api_config.get("endpoints", []):
            item: Dict[str, Any] = {
                "path": endpoint.get("path"),
                "method": endpoint.get("method", "POST"),
                "price_type": endpoint.get("price_type"),
                "description": endpoint.get("description", ""),
            }
            if endpoint.get("example"):
                item["example"] = endpoint["example"]

            if endpoint.get("price_type") == "flat":
                price_sats = int(endpoint.get("price_sats", 0))
                item["price_sats"] = price_sats
                usd_cents = _sats_to_usd_cents(price_sats, btc_usd)
                if usd_cents is not None:
                    item["price_usd_cents"] = usd_cents
            elif endpoint.get("price_type") == "per_model":
                models: Dict[str, Any] = {}
                for model_name, model_entry in endpoint.get("models", {}).items():
                    if isinstance(model_entry, dict):
                        price_sats = int(model_entry.get("price_sats", 0))
                    else:
                        price_sats = int(model_entry)

                    model_item: Dict[str, Any] = {"price_sats": price_sats}
                    usd_cents = _sats_to_usd_cents(price_sats, btc_usd)
                    if usd_cents is not None:
                        model_item["price_usd_cents"] = usd_cents
                    models[model_name] = model_item

                item["models"] = models
            endpoints.append(item)

        apis[api_name] = {
            "name": api_config.get("name"),
            "endpoints": endpoints,
        }

    return {
        "btc_usd": btc_usd,
        "btc_usd_updated_at": btc_usd_updated_at,
        "apis": apis,
    }


def _read_api_key(api_name: str, api_config: Dict[str, Any]) -> str:
    env_name = api_config.get("api_key_env", "")
    value = os.getenv(env_name, "")
    if not value:
        raise RuntimeError(f"missing upstream key: {env_name} for {api_name}")
    return value


def _create_l402_macaroon(
    payment_hash: str, amount_sats: int, account_id: Optional[str] = None,
) -> str:
    macaroon = Macaroon(
        location=L402_LOCATION,
        identifier=payment_hash,
        key=L402_ROOT_KEY,
    )
    macaroon.add_first_party_caveat(f"payment_hash={payment_hash}")
    macaroon.add_first_party_caveat(f"amount_sats={amount_sats}")
    if account_id:
        macaroon.add_first_party_caveat(f"account_id={account_id}")
    return macaroon.serialize()


def _parse_l402_authorization(auth_header: str) -> Tuple[str, str]:
    prefix = "L402 "
    if not auth_header.startswith(prefix):
        raise ValueError("Authorization header must start with 'L402 '")

    payload = auth_header[len(prefix):].strip()
    if ":" not in payload:
        raise ValueError("Authorization header must be 'L402 <macaroon>:<preimage>'")

    macaroon_b64, preimage = payload.rsplit(":", 1)
    if not macaroon_b64.strip() or not preimage.strip():
        raise ValueError("Authorization header must include macaroon and preimage")

    return macaroon_b64.strip(), preimage.strip()


def _resolve_token(request: Request) -> Optional[str]:
    """Extract bearer token from X-Token header. Returns None if absent."""
    x_token = request.headers.get("x-token", "").strip()
    if x_token:
        return x_token
    return None


def _extract_l402_caveats(macaroon: Macaroon) -> Tuple[str, int, Optional[str]]:
    payment_hash: Optional[str] = None
    amount_sats: Optional[int] = None
    account_id: Optional[str] = None

    for caveat in macaroon.caveats:
        caveat_id = getattr(caveat, "caveat_id", "")
        if isinstance(caveat_id, bytes):
            caveat_str = caveat_id.decode("utf-8", "ignore")
        else:
            caveat_str = str(caveat_id)

        key, sep, value = caveat_str.partition("=")
        if sep != "=":
            continue
        key = key.strip()
        value = value.strip()

        if key == "payment_hash":
            if payment_hash is not None:
                raise ValueError("Duplicate payment_hash caveat")
            payment_hash = _canonical_hash(value)
        elif key == "amount_sats":
            if amount_sats is not None:
                raise ValueError("Duplicate amount_sats caveat")
            try:
                amount_sats = int(value)
            except ValueError as exc:
                raise ValueError("amount_sats caveat must be an integer") from exc
        elif key == "account_id":
            account_id = value

    if not payment_hash:
        raise ValueError("Missing payment_hash caveat")
    if amount_sats is None or amount_sats < 0:
        raise ValueError("Missing or invalid amount_sats caveat")

    return payment_hash, amount_sats, account_id


def _verify_l402_macaroon(macaroon_b64: str) -> Tuple[str, int, Optional[str]]:
    try:
        macaroon = Macaroon.deserialize(macaroon_b64)
    except Exception as exc:
        raise ValueError("Invalid macaroon format") from exc

    verifier = Verifier()
    verifier.satisfy_general(lambda _: True)
    try:
        verifier.verify(macaroon, L402_ROOT_KEY)
    except Exception as exc:
        raise ValueError("Invalid macaroon signature") from exc

    return _extract_l402_caveats(macaroon)


async def _proxy_upstream(
    api_name: str,
    normalized_path: str,
    api_config: Dict[str, Any],
    endpoint_config: Dict[str, Any],
    request_bytes: bytes,
    request_content_type: str,
) -> Response:
    upstream_url = f"{api_config.get('upstream_base', '').rstrip('/')}{normalized_path}"
    if not upstream_url.startswith("http"):
        return _build_error(502, "upstream_error", "Invalid upstream URL")

    try:
        api_key = _read_api_key(api_name, api_config)
    except RuntimeError as exc:
        return _build_error(502, "upstream_error", str(exc))

    headers = {
        api_config.get("auth_header", "Authorization"): (
            f"{api_config.get('auth_prefix', '')}{api_key}"
        ),
        "Content-Type": request_content_type or "application/octet-stream",
    }
    headers.update(api_config.get("extra_headers", {}))

    method = endpoint_config.get("method", "POST").upper()
    wants_stream = False
    if normalized_path in {"/v1/chat/completions", "/v1/responses"}:
        try:
            payload = json.loads(request_bytes.decode("utf-8"))
            wants_stream = bool(payload.get("stream"))
        except Exception:
            wants_stream = False

    if wants_stream:
        stream_client = httpx.AsyncClient(timeout=None)
        stream_cm = stream_client.stream(
            method=method,
            url=upstream_url,
            content=request_bytes,
            headers=headers,
        )
        try:
            upstream_response = await stream_cm.__aenter__()
        except httpx.HTTPError as exc:
            await stream_client.aclose()
            return _build_error(502, "upstream_error", f"Upstream request failed: {exc}")

        content_type = upstream_response.headers.get("content-type", "text/event-stream")

        async def stream_chunks() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
            finally:
                await stream_cm.__aexit__(None, None, None)
                await stream_client.aclose()

        return StreamingResponse(
            stream_chunks(),
            status_code=upstream_response.status_code,
            media_type=content_type,
        )

    slow_paths = {
        "/v1/video/generations",
        "/v1/responses",
        "/v1/images/generations",
        "/v1/images/edits",
    }
    upstream_timeout = 600 if normalized_path in slow_paths else 180

    try:
        async with httpx.AsyncClient(timeout=upstream_timeout) as client:
            upstream_response = await client.request(
                method=method,
                url=upstream_url,
                content=request_bytes,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        return _build_error(502, "upstream_error", f"Upstream request failed: {exc}")

    content_type = upstream_response.headers.get("content-type", "application/json")
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        media_type=content_type,
    )


phoenix_url = os.getenv("PHOENIX_URL", CONFIG.get("phoenix", {}).get("url", "http://localhost:9740"))
phoenix_password = os.getenv("PHOENIX_PASSWORD", "")
phoenix_client = PhoenixClient(phoenix_url, phoenix_password)
L402_LOCATION = os.getenv("L402_LOCATION", "alittlebitofmoney")
L402_ROOT_KEY = os.getenv("L402_ROOT_KEY", "").strip()
if not L402_ROOT_KEY:
    L402_ROOT_KEY = secrets.token_hex(32)
    print(
        "WARNING: L402_ROOT_KEY is not set. Generated an ephemeral key; "
        "set L402_ROOT_KEY in .env for stable macaroon verification across restarts."
    )

USED_HASH_TTL_SECONDS = int(CONFIG.get("used_hash_ttl_seconds", 3600))
USED_HASH_CLEANUP_SECONDS = int(CONFIG.get("used_hash_cleanup_interval_seconds", 300))
used_hashes = UsedHashSet(
    ttl_seconds=USED_HASH_TTL_SECONDS,
    cleanup_interval_seconds=USED_HASH_CLEANUP_SECONDS,
)
topup_store = SupabaseTopupStore.from_env()

BTC_PRICE_SOURCE = CONFIG.get("btc_price", {}).get(
    "source",
    "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
)
BTC_PRICE_CACHE_SECONDS = int(CONFIG.get("btc_price", {}).get("cache_seconds", 300))
_btc_usd_price: Optional[float] = None
_btc_usd_updated_at: float = 0.0
_btc_usd_lock = asyncio.Lock()


async def _get_cached_btc_usd() -> Tuple[Optional[float], Optional[str]]:
    global _btc_usd_price, _btc_usd_updated_at

    now = time.time()
    if _btc_usd_price is not None and now - _btc_usd_updated_at < BTC_PRICE_CACHE_SECONDS:
        return _btc_usd_price, _utc_timestamp_iso(_btc_usd_updated_at)

    async with _btc_usd_lock:
        now = time.time()
        if _btc_usd_price is not None and now - _btc_usd_updated_at < BTC_PRICE_CACHE_SECONDS:
            return _btc_usd_price, _utc_timestamp_iso(_btc_usd_updated_at)

        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(str(BTC_PRICE_SOURCE))
                response.raise_for_status()
                payload = response.json()
            maybe_price = payload.get("bitcoin", {}).get("usd")
            if maybe_price is not None:
                _btc_usd_price = float(maybe_price)
                _btc_usd_updated_at = now
        except Exception:
            pass

    return _btc_usd_price, _utc_timestamp_iso(_btc_usd_updated_at)

app = FastAPI(title="alittlebitofmoney")

hire_store: Optional[HireStore] = None
_cleanup_task: Optional[asyncio.Task[None]] = None


async def _cleanup_worker() -> None:
    while True:
        await asyncio.sleep(USED_HASH_CLEANUP_SECONDS)
        used_hashes.cleanup()


@app.on_event("startup")
async def startup() -> None:
    global _cleanup_task, hire_store
    await topup_store.startup()
    if topup_store.pool is not None:
        hire_store = HireStore(topup_store.pool)
        await hire_store.ensure_schema()
        print("Hire store initialized")
    _cleanup_task = asyncio.create_task(_cleanup_worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass
    await topup_store.shutdown()


@app.get("/")
async def root() -> Response:
    return _frontend_index_response()


@app.get("/api/v1/catalog")
async def api_catalog() -> Dict[str, Any]:
    btc_usd, btc_usd_updated_at = await _get_cached_btc_usd()
    return _build_catalog(btc_usd, btc_usd_updated_at)


# ── Machine-readable documentation endpoints ──────────────────────


def _build_llms_txt() -> str:
    """Build plain-text LLM-readable documentation from config."""
    lines = [
        "# aiforhire.xyz — AI API Gateway (Lightning L402)",
        "",
        "> Pay-per-request AI APIs. No signup, no API key.",
        "> Pay with Bitcoin Lightning. All endpoints 10 sats (promo).",
        "",
        "## Authentication",
        "",
        "Every API call uses the L402 protocol (Lightning HTTP 402):",
        "",
        "1. Send your request (no auth header needed on first call)",
        "2. Receive HTTP 402 with a Lightning invoice in the response body",
        "3. Pay the invoice with any Lightning wallet to get a preimage",
        "4. Resend the same request with header:",
        '   Authorization: L402 <macaroon>:<preimage>',
        "",
        "The macaroon and invoice are returned in the 402 response.",
        "The preimage is the proof-of-payment from your Lightning wallet.",
        "",
        "### Example (curl)",
        "",
        "```bash",
        "# Step 1: Get invoice",
        'RESP=$(curl -s https://aiforhire.xyz/api/v1/openai/v1/chat/completions \\',
        "  -H 'Content-Type: application/json' \\",
        '  -d \'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}\')',
        "",
        "# Step 2: Pay the invoice from the response, get preimage",
        "# Step 3: Resend with L402 auth",
        'curl https://aiforhire.xyz/api/v1/openai/v1/chat/completions \\',
        "  -H 'Content-Type: application/json' \\",
        "  -H 'Authorization: L402 <macaroon>:<preimage>' \\",
        '  -d \'{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Hello"}]}\'',
        "```",
        "",
        "## Endpoints",
        "",
    ]

    for api_name, api_config in CONFIG.get("apis", {}).items():
        provider_name = api_config.get("name", api_name)
        lines.append(f"### {provider_name}")
        lines.append("")
        for endpoint in api_config.get("endpoints", []):
            path = endpoint.get("path", "")
            method = endpoint.get("method", "POST")
            desc = endpoint.get("description", "")
            full_path = f"/api/v1/{api_name}{path}"
            lines.append(f"- **{method} {full_path}** — {desc}")

            if endpoint.get("price_type") == "flat":
                price = endpoint.get("price_sats", 10)
                lines.append(f"  Price: {price} sats (flat)")
            elif endpoint.get("price_type") == "per_model":
                models = endpoint.get("models", {})
                model_names = [m for m in models if m != "_default"]
                if model_names:
                    lines.append(f"  Models: {', '.join(model_names)}")
                    prices = set()
                    for m, entry in models.items():
                        if m == "_default":
                            continue
                        p = entry.get("price_sats", 10) if isinstance(entry, dict) else int(entry)
                        prices.add(p)
                    if len(prices) == 1:
                        lines.append(f"  Price: {prices.pop()} sats per request")
                    else:
                        lines.append(f"  Price: {min(prices)}-{max(prices)} sats per request")

            lines.append("")

    lines.extend([
        "## Rate Limits (Promo Period)",
        "",
        "Daily caps per endpoint (resets at midnight UTC):",
    ])
    for path, limit in DAILY_RATE_LIMITS.items():
        if path == "_default":
            lines.append(f"- All other endpoints: {limit}/day")
        else:
            lines.append(f"- {path}: {limit}/day")
    lines.append("")
    lines.append("## More Info")
    lines.append("")
    lines.append("- Website: https://aiforhire.xyz")
    lines.append("- OpenAPI spec: https://aiforhire.xyz/openapi.json")
    lines.append("- AI plugin manifest: https://aiforhire.xyz/.well-known/ai-plugin.json")
    lines.append("")

    return "\n".join(lines)


def _build_openapi_spec() -> Dict[str, Any]:
    """Build OpenAPI 3.1.0 spec dynamically from config."""
    paths: Dict[str, Any] = {}

    for api_name, api_config in CONFIG.get("apis", {}).items():
        for endpoint in api_config.get("endpoints", []):
            ep_path = endpoint.get("path", "")
            method = endpoint.get("method", "POST").lower()
            desc = endpoint.get("description", "")
            full_path = f"/api/v1/{api_name}{ep_path}"

            # Build request body schema
            request_body: Dict[str, Any] = {}
            example_conf = endpoint.get("example", {})
            content_type = example_conf.get("content_type", "json")

            if content_type == "json":
                body_example = example_conf.get("body", {})
                request_body = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                            "example": body_example,
                        }
                    },
                }
            elif content_type == "multipart":
                fields_example = example_conf.get("fields", {})
                properties: Dict[str, Any] = {}
                for field_name, field_val in fields_example.items():
                    if isinstance(field_val, str) and field_val.startswith("@"):
                        properties[field_name] = {
                            "type": "string",
                            "format": "binary",
                            "description": example_conf.get("file_comment", "file upload"),
                        }
                    else:
                        properties[field_name] = {"type": "string", "example": field_val}
                request_body = {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "properties": properties,
                            }
                        }
                    },
                }

            # Build model enum if per_model pricing
            models_list = []
            if endpoint.get("price_type") == "per_model":
                models_list = [m for m in endpoint.get("models", {}) if m != "_default"]

            # Operation object
            operation: Dict[str, Any] = {
                "summary": desc,
                "operationId": f"{api_name}_{ep_path.strip('/').replace('/', '_')}",
                "security": [{"L402": []}],
                "responses": {
                    "200": {"description": "Successful response (format varies by endpoint)"},
                    "402": {
                        "description": "Payment required — pay the Lightning invoice to proceed",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "payment_hash": {"type": "string"},
                                        "invoice": {"type": "string", "description": "Lightning BOLT11 invoice"},
                                        "amount_sats": {"type": "integer"},
                                        "macaroon": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                },
                            }
                        },
                    },
                    "429": {"description": "Daily rate limit exceeded"},
                },
            }
            if request_body:
                operation["requestBody"] = request_body
            if models_list:
                operation["x-supported-models"] = models_list

            if full_path not in paths:
                paths[full_path] = {}
            paths[full_path][method] = operation

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "aiforhire.xyz — AI API Gateway",
            "description": (
                "Pay-per-request AI APIs via Bitcoin Lightning (L402 protocol). "
                "No signup, no API key. Supports OpenAI, Anthropic, and OpenRouter models."
            ),
            "version": "1.0.0",
            "contact": {"url": "https://aiforhire.xyz"},
        },
        "servers": [{"url": "https://aiforhire.xyz"}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "L402": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": (
                        "L402 authentication. Format: 'L402 <macaroon>:<preimage>'. "
                        "Obtain macaroon and invoice from any 402 response, pay the "
                        "Lightning invoice to get the preimage, then include both."
                    ),
                }
            }
        },
    }


def _build_ai_plugin_manifest() -> Dict[str, Any]:
    """Build AI plugin manifest (ChatGPT plugin / agent discovery format)."""
    return {
        "schema_version": "v1",
        "name_for_human": "AI for Hire",
        "name_for_model": "aiforhire",
        "description_for_human": (
            "Pay-per-request AI APIs via Bitcoin Lightning. "
            "No signup, no API key. GPT, Claude, Whisper, DALL-E, Sora and more."
        ),
        "description_for_model": (
            "AI API gateway that provides access to OpenAI, Anthropic, and OpenRouter "
            "models via Bitcoin Lightning micropayments (L402 protocol). Send a request "
            "to any endpoint, receive a 402 with a Lightning invoice, pay it, then "
            "resend with the L402 Authorization header. All endpoints are currently "
            "10 sats during the promo period."
        ),
        "auth": {
            "type": "none",
            "instructions": (
                "No pre-registration needed. Authentication happens per-request via "
                "L402 (Lightning 402). Send your request, pay the returned invoice, "
                "then resend with 'Authorization: L402 <macaroon>:<preimage>'."
            ),
        },
        "api": {
            "type": "openapi",
            "url": "https://aiforhire.xyz/openapi.json",
        },
        "logo_url": "https://aiforhire.xyz/logo.png",
        "contact_email": "",
        "legal_info_url": "https://aiforhire.xyz",
    }


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt() -> Response:
    return Response(content=_build_llms_txt(), media_type="text/plain; charset=utf-8")


@app.get("/openapi.json", include_in_schema=False)
async def openapi_spec() -> JSONResponse:
    return JSONResponse(content=_build_openapi_spec())


@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
async def ai_plugin_manifest() -> JSONResponse:
    return JSONResponse(content=_build_ai_plugin_manifest())


@app.get("/api/v1/health")
async def health() -> Response:
    phoenix_status: dict = {"ok": False}
    try:
        balance = await phoenix_client.get_balance()
        phoenix_status = {"ok": True, "balance": balance}
    except PhoenixError as exc:
        phoenix_status = {"ok": False, "error": str(exc)}

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "timestamp": int(time.time()),
            "phoenix": phoenix_status,
            "invoices": used_hashes.stats(),
            "topup": {"enabled": topup_store.enabled, "ready": topup_store.ready},
        },
    )


@app.get("/.well-known/satring-verify")
async def satring_verify() -> Response:
    if not SATRING_VERIFY_PATH.exists():
        return _build_error(404, "not_found", "Route not found")

    try:
        payload = SATRING_VERIFY_PATH.read_text(encoding="utf-8")
    except Exception:
        return _build_error(500, "server_error", "Could not read verification payload")

    return Response(content=payload, media_type="text/plain")


@app.post("/api/v1/topup")
async def create_topup_invoice(request: Request) -> Response:
    if not topup_store.ready:
        return _build_error(503, "topup_unavailable", "Topup service is not configured")

    token = _resolve_token(request)
    account_id: Optional[str] = None
    if token is not None:
        try:
            account_id = await topup_store.get_account_id_by_token(token)
        except TopupInvalidToken:
            return _build_error(401, "invalid_token", "Unknown X-Token")
        except RuntimeError:
            return _build_error(503, "topup_unavailable", "Topup service is not configured")

    try:
        payload = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    if not isinstance(payload, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    amount_raw = payload.get("amount_sats")
    try:
        amount_sats = int(amount_raw)
    except (TypeError, ValueError):
        return _build_error(400, "invalid_amount", "amount_sats must be a positive integer")
    if amount_sats <= 0:
        return _build_error(400, "invalid_amount", "amount_sats must be a positive integer")

    try:
        created_invoice = await phoenix_client.create_invoice(
            amount_sats=amount_sats,
            description="topup",
        )
    except PhoenixError as exc:
        return _build_error(503, "phoenix_unavailable", str(exc))

    payment_hash = _canonical_hash(created_invoice.get("paymentHash", ""))
    invoice = created_invoice.get("serialized", "")
    if not payment_hash or not invoice:
        return _build_error(503, "phoenix_unavailable", "Invalid invoice payload from phoenixd")

    try:
        await topup_store.create_topup_invoice(
            payment_hash=payment_hash,
            amount_sats=amount_sats,
            account_id=account_id,
        )
    except RuntimeError:
        return _build_error(503, "topup_unavailable", "Topup service is not configured")

    expires_in = int(CONFIG.get("invoice_expiry", 600))
    response = JSONResponse(
        status_code=402,
        content={
            "status": "payment_required",
            "payment_method": "topup",
            "invoice": invoice,
            "payment_hash": payment_hash,
            "amount_sats": amount_sats,
            "expires_in": expires_in,
            "claim_url": "/api/v1/topup/claim",
        },
    )
    response.headers["X-Lightning-Invoice"] = invoice
    response.headers["X-Payment-Hash"] = payment_hash
    response.headers["X-Price-Sats"] = str(amount_sats)
    response.headers["X-Topup-Claim-URL"] = "/api/v1/topup/claim"
    return response


@app.post("/api/v1/topup/claim")
async def claim_topup_invoice(request: Request) -> Response:
    if not topup_store.ready:
        return _build_error(503, "topup_unavailable", "Topup service is not configured")

    try:
        payload = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    if not isinstance(payload, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    preimage = payload.get("preimage")
    if not isinstance(preimage, str) or not preimage.strip():
        return _build_error(400, "invalid_payment", "Missing preimage")

    raw_token = payload.get("token")
    token: Optional[str] = None
    if raw_token is not None:
        if not isinstance(raw_token, str) or not raw_token.strip():
            return _build_error(400, "invalid_token", "token must be a non-empty string")
        token = raw_token.strip()

    try:
        payment_hash = _canonical_hash(_hash_from_preimage(preimage))
    except ValueError as exc:
        return _build_error(400, "invalid_payment", str(exc))

    try:
        claim = await topup_store.claim_topup_invoice(
            payment_hash=payment_hash,
            token=token,
        )
    except TopupInvalidPayment:
        return _build_error(400, "invalid_payment", "Unknown topup payment hash")
    except TopupInvoiceAlreadyClaimed:
        return _build_error(400, "payment_already_used", "Topup invoice already claimed")
    except TopupInvalidToken:
        return _build_error(401, "invalid_token", "Unknown topup token")
    except TopupMissingToken:
        return _build_error(400, "missing_token", "token is required to claim refill invoices")
    except RuntimeError:
        return _build_error(503, "topup_unavailable", "Topup service is not configured")

    return JSONResponse(
        status_code=200,
        content={
            "token": claim.token,
            "balance_sats": claim.balance_sats,
        },
    )


def _require_hire() -> HireStore:
    if hire_store is None:
        raise RuntimeError("hire service not available")
    return hire_store


# ── AI for Hire auth: X-Token (identity) + L402 (payment) ────────

class _HireAuth:
    """Result of hire auth resolution."""
    __slots__ = ("account_id", "method", "l402_amount_sats", "l402_payment_hash")

    def __init__(
        self,
        account_id: Optional[str],
        method: str,
        l402_amount_sats: int = 0,
        l402_payment_hash: str = "",
    ) -> None:
        self.account_id = account_id
        self.method = method
        self.l402_amount_sats = l402_amount_sats
        self.l402_payment_hash = l402_payment_hash


async def _hire_resolve_auth(request: Request) -> "_HireAuth | Response":
    """
    Resolve hire caller identity.

    Checks X-Token header for account identity. Checks Authorization: L402 for
    payment proof. Both can be present simultaneously (no header collision).
    L402 payment is verified but NOT consumed — caller must call
    _hire_consume_l402() after any amount checks.
    """
    token = _resolve_token(request)
    auth_header = request.headers.get("authorization", "").strip()
    has_l402 = auth_header.startswith("L402 ")

    account_id: Optional[str] = None
    if token:
        try:
            account_id = await topup_store.get_account_id_by_token(token)
        except TopupInvalidToken:
            return _build_error(401, "invalid_token", "Unknown X-Token")

    if has_l402:
        try:
            macaroon_b64, preimage = _parse_l402_authorization(auth_header)
            payment_hash, paid_amount, l402_account_id = _verify_l402_macaroon(macaroon_b64)
        except ValueError as exc:
            return _build_error(401, "invalid_l402", str(exc))

        try:
            derived = _canonical_hash(_hash_from_preimage(preimage))
        except ValueError as exc:
            return _build_error(400, "invalid_payment", str(exc))

        if derived != payment_hash:
            return _build_error(401, "invalid_l402", "Preimage does not match payment_hash")

        if used_hashes.is_used(payment_hash):
            return _build_error(400, "payment_already_used", "Payment hash already redeemed")

        # If L402 macaroon has account_id caveat, use it (unless X-Token overrides)
        resolved_account_id = account_id or l402_account_id
        return _HireAuth(
            account_id=resolved_account_id,
            method="l402",
            l402_amount_sats=paid_amount,
            l402_payment_hash=payment_hash,
        )

    if account_id:
        return _HireAuth(account_id=account_id, method="token")

    # No auth at all
    return _HireAuth(account_id=None, method="none")


def _hire_consume_l402(
    auth: _HireAuth, min_sats: int = 0,
) -> Optional[Response]:
    """
    Consume an L402 payment (mark hash used). No-op for token auth.

    Returns an error Response if the L402 amount is insufficient or was already
    used; returns None on success.
    """
    if auth.method != "l402":
        return None
    if min_sats > 0 and auth.l402_amount_sats < min_sats:
        return _build_error(
            402,
            "insufficient_payment",
            f"Need {min_sats} sats, L402 authorizes {auth.l402_amount_sats}",
        )
    if not used_hashes.mark_used(auth.l402_payment_hash):
        return _build_error(400, "payment_already_used", "Payment hash already redeemed")
    return None


async def _hire_402_challenge(
    price_sats: int,
    description: str,
    account_id: Optional[str] = None,
    new_token: Optional[str] = None,
) -> Response:
    """Issue a 402 L402 challenge for a hire endpoint.

    If new_token is provided, it's included in the response so the client can
    save it for future requests (auto-account-creation flow).
    """
    invoice_amount = max(price_sats, 1)
    try:
        created_invoice = await phoenix_client.create_invoice(
            amount_sats=invoice_amount,
            description=f"hire:{description}",
        )
    except PhoenixError as exc:
        return _build_error(503, "phoenix_unavailable", str(exc))

    payment_hash = _canonical_hash(created_invoice.get("paymentHash", ""))
    invoice = created_invoice.get("serialized", "")
    if not payment_hash or not invoice:
        return _build_error(503, "phoenix_unavailable", "Invalid invoice from phoenixd")

    macaroon_b64 = _create_l402_macaroon(payment_hash, invoice_amount, account_id=account_id)
    expires_in = int(CONFIG.get("invoice_expiry", 600))
    body: Dict[str, Any] = {
        "status": "payment_required",
        "invoice": invoice,
        "payment_hash": payment_hash,
        "amount_sats": invoice_amount,
        "expires_in": expires_in,
    }
    if new_token:
        body["token"] = new_token
    response = JSONResponse(status_code=402, content=body)
    response.headers["WWW-Authenticate"] = (
        f'L402 macaroon="{macaroon_b64}", invoice="{invoice}"'
    )
    response.headers["X-Lightning-Invoice"] = invoice
    response.headers["X-Payment-Hash"] = payment_hash
    response.headers["X-Price-Sats"] = str(invoice_amount)
    if topup_store.ready:
        response.headers["X-Topup-URL"] = "/api/v1/topup"
    return response


async def _hire_require_paid(
    request: Request,
    price_sats: int,
    description: str,
) -> "tuple[_HireAuth, Optional[Response]]":
    """
    Require payment for a hire endpoint (POST task = 50 sats, POST quote = 10 sats).

    Returns (auth, None) on success, or (auth, error_response) on failure.

    Flow:
    - X-Token present + sufficient balance → debit and proceed
    - X-Token present + insufficient balance → 402 challenge (with account_id in macaroon)
    - L402 present (with or without X-Token) → verify amount ≥ price_sats
    - No auth → auto-create account with 0 balance, return 402 + new token
    """
    auth = await _hire_resolve_auth(request)
    if isinstance(auth, Response):
        return _HireAuth(account_id=None, method="none"), auth

    # L402 payment — verify amount covers price
    if auth.method == "l402":
        err = _hire_consume_l402(auth, min_sats=price_sats)
        if err:
            return auth, err
        return auth, None

    # X-Token auth — debit balance
    if auth.method == "token" and auth.account_id:
        try:
            await topup_store.debit_token_balance(
                token=_resolve_token(request),
                amount_sats=price_sats,
                endpoint=f"hire:{description}",
            )
        except TopupInsufficientBalance:
            challenge = await _hire_402_challenge(
                price_sats=price_sats,
                description=description,
                account_id=auth.account_id,
            )
            return auth, challenge
        return auth, None

    # No auth — auto-create account, return 402 with new token
    try:
        new_account_id, new_token = await topup_store.create_account()
    except Exception:
        return auth, _build_error(503, "topup_unavailable", "Cannot create account")
    challenge = await _hire_402_challenge(
        price_sats=price_sats,
        description=description,
        account_id=new_account_id,
        new_token=new_token,
    )
    return auth, challenge


def _hire_require_identity(
    auth: "_HireAuth | Response",
) -> Optional[Response]:
    """Return an error Response if the auth has no account identity, else None."""
    if isinstance(auth, Response):
        return auth
    if not auth.account_id:
        return _build_error(
            401, "account_required",
            "This endpoint requires X-Token header for account identity.",
        )
    return None


# ── AI for Hire endpoints ─────────────────────────────────────────


@app.get("/api/v1/ai-for-hire/me")
async def hire_me(request: Request) -> Response:
    """Account info. Requires X-Token (free, no sats cost)."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        info = await store.get_account_info(auth.account_id)
    except HireNotFound:
        return _build_error(404, "not_found", "Account not found")
    return JSONResponse(info)


@app.post("/api/v1/ai-for-hire/tasks")
async def hire_create_task(request: Request) -> Response:
    """Post a new task. Costs 50 sats (X-Token balance or L402)."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth, err = await _hire_require_paid(request, price_sats=50, description="post_task")
    if err:
        return err
    if not auth.account_id:
        return _build_error(401, "account_required",
                            "This endpoint requires account identity.")

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    title = body.get("title", "").strip()
    if not title:
        return _build_error(400, "missing_field", "title is required")
    description = body.get("description", "")
    try:
        budget_sats = int(body.get("budget_sats", 0))
    except (TypeError, ValueError):
        return _build_error(400, "invalid_field", "budget_sats must be a positive integer")
    if budget_sats <= 0:
        return _build_error(400, "invalid_field", "budget_sats must be a positive integer")

    try:
        task = await store.create_task(auth.account_id, title, description, budget_sats)
    except HireError as exc:
        return _build_error(400, "hire_error", str(exc))
    return JSONResponse(task, status_code=201)


@app.get("/api/v1/ai-for-hire/tasks")
async def hire_list_tasks(request: Request) -> Response:
    """List tasks. Free, no auth required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    status_filter = request.query_params.get("status")
    tasks = await store.list_tasks(status=status_filter)
    return JSONResponse({"tasks": tasks})


@app.get("/api/v1/ai-for-hire/tasks/{task_id}")
async def hire_get_task(task_id: str, request: Request) -> Response:
    """Get task detail. Free, no auth required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    try:
        detail = await store.get_task_detail(task_id)
    except HireNotFound:
        return _build_error(404, "not_found", "Task not found")
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task ID")
    return JSONResponse(detail)


@app.post("/api/v1/ai-for-hire/tasks/{task_id}/quotes")
async def hire_create_quote(task_id: str, request: Request) -> Response:
    """Submit a quote. Costs 10 sats (X-Token balance or L402)."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth, err = await _hire_require_paid(request, price_sats=10, description="post_quote")
    if err:
        return err
    if not auth.account_id:
        return _build_error(401, "account_required",
                            "This endpoint requires account identity.")

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    try:
        price_sats = int(body.get("price_sats", 0))
    except (TypeError, ValueError):
        return _build_error(400, "invalid_field", "price_sats must be a positive integer")
    if price_sats <= 0:
        return _build_error(400, "invalid_field", "price_sats must be a positive integer")
    description = body.get("description", "")

    try:
        quote = await store.create_quote(task_id, auth.account_id, price_sats, description)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task ID")
    return JSONResponse(quote, status_code=201)


@app.post("/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/accept")
async def hire_accept_quote(task_id: str, quote_id: str, request: Request) -> Response:
    """Accept a quote and lock escrow. Free, X-Token required. Buyer needs sufficient balance."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    # Consume L402 if present (no-op for token auth)
    err = _hire_consume_l402(auth)
    if err:
        return err

    # Debit buyer balance for escrow; on insufficient balance issue 402
    try:
        result = await store.accept_quote(task_id, quote_id, auth.account_id)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except HireInsufficientBalance as exc:
        return await _hire_402_challenge(
            price_sats=exc.required_sats,
            description=f"escrow:{task_id}",
            account_id=auth.account_id,
        )
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task or quote ID")
    return JSONResponse(result)


@app.patch("/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}")
async def hire_update_quote(task_id: str, quote_id: str, request: Request) -> Response:
    """Update a pending quote (contractor only). Free, X-Token required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    price_sats = None
    if "price_sats" in body:
        try:
            price_sats = int(body["price_sats"])
        except (TypeError, ValueError):
            return _build_error(400, "invalid_field", "price_sats must be a positive integer")
        if price_sats <= 0:
            return _build_error(400, "invalid_field", "price_sats must be a positive integer")
    description = body.get("description")

    try:
        result = await store.update_quote(task_id, quote_id, auth.account_id,
                                          price_sats=price_sats, description=description)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except HireError as exc:
        return _build_error(400, "hire_error", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task or quote ID")
    return JSONResponse(result)


@app.post("/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/messages")
async def hire_send_quote_message(task_id: str, quote_id: str, request: Request) -> Response:
    """Send a message on a quote thread. Free, X-Token required. Buyer or contractor only."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    text = body.get("body", "").strip()
    if not text:
        return _build_error(400, "missing_field", "body is required")

    try:
        msg = await store.send_quote_message(task_id, quote_id, auth.account_id, text)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task or quote ID")
    return JSONResponse(msg, status_code=201)


@app.get("/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/messages")
async def hire_get_quote_messages(task_id: str, quote_id: str, request: Request) -> Response:
    """Get messages on a quote thread. Free, X-Token required. Buyer or contractor only."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        since_id = int(request.query_params.get("since_id", "0"))
    except (TypeError, ValueError):
        since_id = 0

    try:
        messages = await store.get_quote_messages(task_id, quote_id, auth.account_id, since_id=since_id)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task or quote ID")
    return JSONResponse({"messages": messages})


@app.post("/api/v1/ai-for-hire/tasks/{task_id}/deliver")
async def hire_deliver(task_id: str, request: Request) -> Response:
    """Upload delivery. Free, X-Token required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    filename = body.get("filename", "")
    content_base64 = body.get("content_base64", "")
    notes = body.get("notes", "")

    try:
        delivery = await store.create_delivery(task_id, auth.account_id, filename, content_base64, notes)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task ID")
    return JSONResponse(delivery, status_code=201)


@app.post("/api/v1/ai-for-hire/tasks/{task_id}/confirm")
async def hire_confirm(task_id: str, request: Request) -> Response:
    """Confirm delivery and release escrow. Free, X-Token required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        result = await store.confirm_delivery(task_id, auth.account_id)
    except HireNotFound as exc:
        return _build_error(404, "not_found", str(exc))
    except HireInvalidState as exc:
        return _build_error(409, "invalid_state", str(exc))
    except HireForbidden as exc:
        return _build_error(403, "forbidden", str(exc))
    except Exception:
        return _build_error(400, "invalid_request", "Invalid task ID")
    return JSONResponse(result)


@app.post("/api/v1/ai-for-hire/collect")
async def hire_collect(request: Request) -> Response:
    """Withdraw balance via Lightning invoice. Free, X-Token required."""
    try:
        store = _require_hire()
    except RuntimeError:
        return _build_error(503, "hire_unavailable", "AI for Hire is not available")

    auth = await _hire_resolve_auth(request)
    err = _hire_require_identity(auth)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return _build_error(400, "invalid_request", "Request body must be JSON")
    if not isinstance(body, dict):
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    bolt11 = body.get("invoice", "").strip()
    if not bolt11:
        return _build_error(400, "missing_field", "invoice (bolt11) is required")

    try:
        amount_sats = int(body.get("amount_sats", 0))
    except (TypeError, ValueError):
        return _build_error(400, "invalid_field", "amount_sats must be a positive integer")
    if amount_sats <= 0:
        return _build_error(400, "invalid_field", "amount_sats must be a positive integer")

    # Debit account balance
    try:
        await store.debit_account(auth.account_id, amount_sats, "hire:collect")
    except HireInsufficientBalance as exc:
        return _build_error(
            402, "insufficient_balance",
            f"Need {exc.required_sats} sats but account balance is insufficient.",
        )

    # Pay the LN invoice
    try:
        pay_result = await phoenix_client.pay_invoice(bolt11)
    except PhoenixError as exc:
        # Refund on failure
        try:
            await store.credit_account(auth.account_id, amount_sats)
        except Exception:
            pass
        return _build_error(502, "payment_failed", f"Lightning payment failed: {exc}")

    return JSONResponse({
        "status": "paid",
        "amount_sats": amount_sats,
        "payment": pay_result,
    })


@app.post("/api/v1/{api_name}/{endpoint_path:path}")
async def create_payment_required(
    api_name: str,
    endpoint_path: str,
    request: Request,
) -> Response:
    api_config, endpoint_config, normalized_path = _resolve_api_endpoint(
        api_name, endpoint_path, request.method
    )
    if api_config is None or endpoint_config is None:
        return _build_error(404, "api_not_found", "Requested endpoint is not configured")

    body_bytes = await request.body()
    max_bytes = _max_request_bytes(endpoint_config)
    if len(body_bytes) > max_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": f"Max request size: {max_bytes} bytes",
                    "max_bytes": max_bytes,
                }
            },
        )

    incoming_content_type = request.headers.get("content-type", "")
    content_type_lc = incoming_content_type.lower()
    is_json = "application/json" in content_type_lc

    request_body: Dict[str, Any] = {}
    stored_body_bytes = body_bytes
    stored_content_type = incoming_content_type or "application/json"

    requires_json = normalized_path in {
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/images/generations",
        "/v1/audio/speech",
        "/v1/embeddings",
        "/v1/moderations",
        "/v1/video/generations",
    }

    if requires_json and not is_json:
        return _build_error(400, "invalid_request", "Request body must be a JSON object")

    if is_json:
        try:
            parsed_body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
        except Exception:
            return _build_error(400, "invalid_request", "Request body must be a JSON object")
        if not isinstance(parsed_body, dict):
            return _build_error(400, "invalid_request", "Request body must be a JSON object")
        request_body = parsed_body
        try:
            request_body = _apply_request_rules(normalized_path, endpoint_config, request_body)
        except LookupError as exc:
            model_name = str(exc).split(":", 1)[-1]
            return _build_error(
                400,
                "model_not_supported",
                f"Model '{model_name}' is not available",
            )

        validation_error = _validate_required_fields(normalized_path, request_body)
        if validation_error is not None:
            return validation_error

        stored_body_bytes = json.dumps(
            request_body, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        stored_content_type = "application/json"

    try:
        amount_sats = _price_for_request(endpoint_config, request_body)
    except LookupError as exc:
        model_name = str(exc).split(":", 1)[-1]
        return _build_error(
            400,
            "model_not_supported",
            f"Model '{model_name}' is not available",
        )
    except Exception as exc:
        return _build_error(500, "server_error", f"Could not price request: {exc}")

    rate_limit_msg = _check_daily_limit(normalized_path)
    if rate_limit_msg is not None:
        return _build_error(429, "daily_limit_reached", rate_limit_msg)

    token = _resolve_token(request)
    auth_header = request.headers.get("authorization", "").strip()
    has_l402_auth = auth_header.startswith("L402 ")

    if token:
        if not topup_store.ready:
            return _build_error(503, "topup_unavailable", "Topup service is not configured")
        try:
            await topup_store.debit_token_balance(
                token=token,
                amount_sats=amount_sats,
                endpoint=f"{api_name}:{normalized_path}",
            )
        except TopupInvalidToken:
            return _build_error(401, "invalid_token", "Unknown X-Token")
        except TopupInsufficientBalance as exc:
            return _build_error(
                402,
                "insufficient_balance",
                (
                    f"Request costs {exc.required_sats} sats, but token balance is "
                    f"{exc.balance_sats} sats."
                ),
            )
        except RuntimeError:
            return _build_error(503, "topup_unavailable", "Topup service is not configured")

        return await _proxy_upstream(
            api_name=api_name,
            normalized_path=normalized_path,
            api_config=api_config,
            endpoint_config=endpoint_config,
            request_bytes=stored_body_bytes,
            request_content_type=stored_content_type,
        )

    if has_l402_auth:
        try:
            macaroon_b64, preimage = _parse_l402_authorization(auth_header)
            payment_hash, paid_amount_sats, _ = _verify_l402_macaroon(macaroon_b64)
        except ValueError as exc:
            return _build_error(401, "invalid_l402", str(exc))

        try:
            derived_payment_hash = _canonical_hash(_hash_from_preimage(preimage))
        except ValueError as exc:
            return _build_error(400, "invalid_payment", str(exc))

        if derived_payment_hash != payment_hash:
            return _build_error(
                401,
                "invalid_l402",
                "Preimage does not match macaroon payment_hash",
            )

        if used_hashes.is_used(payment_hash):
            return _build_error(400, "payment_already_used", "Payment hash already redeemed")

        if amount_sats > paid_amount_sats:
            return _build_error(
                402,
                "insufficient_payment",
                (
                    f"Request costs {amount_sats} sats, but this macaroon only authorizes "
                    f"{paid_amount_sats} sats."
                ),
            )

        if not used_hashes.mark_used(payment_hash):
            return _build_error(400, "payment_already_used", "Payment hash already redeemed")

        return await _proxy_upstream(
            api_name=api_name,
            normalized_path=normalized_path,
            api_config=api_config,
            endpoint_config=endpoint_config,
            request_bytes=stored_body_bytes,
            request_content_type=stored_content_type,
        )

    try:
        created_invoice = await phoenix_client.create_invoice(
            amount_sats=amount_sats,
            description=f"{api_name}:{normalized_path}",
        )
    except PhoenixError as exc:
        return _build_error(503, "phoenix_unavailable", str(exc))

    payment_hash = _canonical_hash(created_invoice.get("paymentHash", ""))
    invoice = created_invoice.get("serialized", "")
    if not payment_hash or not invoice:
        return _build_error(503, "phoenix_unavailable", "Invalid invoice payload from phoenixd")

    macaroon_b64 = _create_l402_macaroon(payment_hash, amount_sats)
    expires_in = int(CONFIG.get("invoice_expiry", 600))
    response = JSONResponse(
        status_code=402,
        content={
            "status": "payment_required",
            "invoice": invoice,
            "payment_hash": payment_hash,
            "amount_sats": amount_sats,
            "expires_in": expires_in,
        },
    )
    response.headers["WWW-Authenticate"] = (
        f'L402 macaroon="{macaroon_b64}", invoice="{invoice}"'
    )
    response.headers["X-Lightning-Invoice"] = invoice
    response.headers["X-Payment-Hash"] = payment_hash
    response.headers["X-Price-Sats"] = str(amount_sats)
    if topup_store.ready:
        response.headers["X-Topup-URL"] = "/api/v1/topup"
    return response


@app.get("/{full_path:path}", include_in_schema=False)
async def frontend_catchall(full_path: str) -> Response:
    static_file = _resolve_frontend_file(full_path)
    if static_file is not None:
        return FileResponse(static_file)

    reserved_root = full_path.split("/", 1)[0]
    if reserved_root in {"api"}:
        return _build_error(404, "not_found", "Route not found")

    return _frontend_index_response()
