from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import httpx
import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from lib.invoice_store import InvoiceRecord, InvoiceStore
from lib.phoenix import PhoenixClient, PhoenixError


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"
PUBLIC_DIR = BASE_DIR / "public"
PUBLIC_INDEX = PUBLIC_DIR / "index.html"
PUBLIC_CATALOG = PUBLIC_DIR / "catalog.html"
PUBLIC_DOC = PUBLIC_DIR / "doc.html"

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
        return ""

    try:
        raw = bytes.fromhex(preimage)
    except ValueError:
        raw = preimage.encode("utf-8")

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


phoenix_url = os.getenv("PHOENIX_URL", CONFIG.get("phoenix", {}).get("url", "http://localhost:9740"))
phoenix_password = os.getenv("PHOENIX_PASSWORD", "")
phoenix_client = PhoenixClient(phoenix_url, phoenix_password)
invoice_store = InvoiceStore(
    invoice_ttl_seconds=1800,
    used_hash_ttl_seconds=3600,
    cleanup_interval_seconds=300,
)

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
app.mount("/assets", StaticFiles(directory=PUBLIC_DIR / "assets"), name="assets")

_cleanup_task: Optional[asyncio.Task[None]] = None


async def _cleanup_worker() -> None:
    while True:
        await asyncio.sleep(300)
        invoice_store.cleanup()


@app.on_event("startup")
async def startup() -> None:
    global _cleanup_task
    _cleanup_task = asyncio.create_task(_cleanup_worker())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _cleanup_task is not None:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass


@app.get("/")
async def root() -> Response:
    return FileResponse(PUBLIC_INDEX)


@app.get("/catalog")
async def catalog_page() -> Response:
    return FileResponse(PUBLIC_CATALOG)


@app.get("/doc")
async def doc_page() -> Response:
    return FileResponse(PUBLIC_DOC)


@app.get("/api/catalog")
async def api_catalog() -> Dict[str, Any]:
    btc_usd, btc_usd_updated_at = await _get_cached_btc_usd()
    return _build_catalog(btc_usd, btc_usd_updated_at)


@app.get("/health")
async def health() -> Response:
    try:
        balance = await phoenix_client.get_balance()
    except PhoenixError as exc:
        return _build_error(503, "phoenix_unavailable", str(exc))

    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "timestamp": int(time.time()),
            "phoenix": {"ok": True, "balance": balance},
            "invoices": invoice_store.stats(),
        },
    )


@app.post("/{api_name}/{endpoint_path:path}")
@app.post("/v1/{api_name}/{endpoint_path:path}", include_in_schema=False)
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

    invoice_store.add(
        payment_hash,
        InvoiceRecord(
            invoice=invoice,
            api_name=api_name,
            endpoint_path=normalized_path,
            amount_sats=amount_sats,
            request_bytes=stored_body_bytes,
            request_content_type=stored_content_type,
            created_at=time.time(),
        ),
    )

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
    response.headers["X-Lightning-Invoice"] = invoice
    response.headers["X-Payment-Hash"] = payment_hash
    response.headers["X-Price-Sats"] = str(amount_sats)
    return response


@app.get("/redeem")
async def redeem(preimage: Optional[str] = None) -> Response:
    if not preimage:
        return _build_error(400, "invalid_payment", "Missing preimage")

    payment_hash = _canonical_hash(_hash_from_preimage(preimage))
    if not payment_hash:
        return _build_error(400, "invalid_payment", "Missing preimage")

    invoice_record = invoice_store.get(payment_hash)
    if invoice_record is None:
        if invoice_store.is_used(payment_hash):
            return _build_error(400, "payment_already_used", "Payment hash already redeemed")
        return _build_error(400, "invalid_payment", "Unknown payment hash")

    if invoice_record.status == "used" or invoice_store.is_used(payment_hash):
        return _build_error(400, "payment_already_used", "Payment hash already redeemed")

    if invoice_store.is_expired(payment_hash, int(CONFIG.get("invoice_expiry", 600))):
        invoice_store.delete(payment_hash)
        return _build_error(410, "invoice_expired", "Invoice has expired")

    if not invoice_store.mark_used(payment_hash):
        return _build_error(400, "payment_already_used", "Payment hash already redeemed")

    api_config = CONFIG.get("apis", {}).get(invoice_record.api_name)
    if api_config is None:
        return _build_error(502, "upstream_error", "Stored API config no longer exists")

    _, endpoint_config, _ = _resolve_api_endpoint(
        invoice_record.api_name, invoice_record.endpoint_path, "POST"
    )
    if endpoint_config is None:
        return _build_error(502, "upstream_error", "Stored endpoint config no longer exists")

    upstream_url = f"{api_config.get('upstream_base', '').rstrip('/')}{invoice_record.endpoint_path}"
    if not upstream_url.startswith("http"):
        return _build_error(502, "upstream_error", "Invalid upstream URL")

    try:
        api_key = _read_api_key(invoice_record.api_name, api_config)
    except RuntimeError as exc:
        return _build_error(502, "upstream_error", str(exc))

    headers = {
        api_config.get("auth_header", "Authorization"): (
            f"{api_config.get('auth_prefix', '')}{api_key}"
        ),
        "Content-Type": invoice_record.request_content_type or "application/octet-stream",
    }
    headers.update(api_config.get("extra_headers", {}))

    method = endpoint_config.get("method", "POST").upper()
    wants_stream = False
    if invoice_record.endpoint_path in {"/v1/chat/completions", "/v1/responses"}:
        try:
            payload = json.loads(invoice_record.request_bytes.decode("utf-8"))
            wants_stream = bool(payload.get("stream"))
        except Exception:
            wants_stream = False

    if wants_stream:
        stream_client = httpx.AsyncClient(timeout=None)
        stream_cm = stream_client.stream(
            method=method,
            url=upstream_url,
            content=invoice_record.request_bytes,
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

    # Video generation and responses API can take longer than text endpoints
    _slow_paths = {"/v1/video/generations", "/v1/responses", "/v1/images/generations", "/v1/images/edits"}
    upstream_timeout = 600 if invoice_record.endpoint_path in _slow_paths else 180

    try:
        async with httpx.AsyncClient(timeout=upstream_timeout) as client:
            upstream_response = await client.request(
                method=method,
                url=upstream_url,
                content=invoice_record.request_bytes,
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
