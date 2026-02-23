# Pricing & Token Caps Spec

## Overview

The proxy must enforce output token caps and request body size limits per model to bound worst-case costs. This ensures flat-rate sats pricing always covers upstream API costs.

At ~$100K/BTC, 1 sat ≈ $0.001.

## Config (config.yaml)

Replace the existing config with this:

```yaml
server:
  port: 3000

phoenix:
  url: "http://localhost:9740"

margin_percent: 5
min_sats: 20
invoice_expiry: 600
max_request_bytes: 32768  # 32KB global default

apis:
  openai:
    name: "OpenAI"
    upstream_base: "https://api.openai.com"
    api_key_env: "OPENAI_API_KEY"
    auth_header: "Authorization"
    auth_prefix: "Bearer "
    endpoints:
      - path: "/v1/chat/completions"
        method: "POST"
        price_type: "per_model"
        description: "Chat completions"
        max_request_bytes: 32768
        models:
          gpt-4o-mini:
            price_sats: 50
            max_output_tokens: 2000
          gpt-4.1-nano:
            price_sats: 50
            max_output_tokens: 2000
          gpt-4.1-mini:
            price_sats: 100
            max_output_tokens: 2000
          gpt-4o:
            price_sats: 500
            max_output_tokens: 2000
          gpt-4.1:
            price_sats: 500
            max_output_tokens: 2000
          gpt-5-mini:
            price_sats: 150
            max_output_tokens: 2000
          gpt-5:
            price_sats: 600
            max_output_tokens: 2000
          gpt-5.1:
            price_sats: 600
            max_output_tokens: 2000
          gpt-5.2:
            price_sats: 800
            max_output_tokens: 2000
          _default:
            price_sats: 800
            max_output_tokens: 1000

      - path: "/v1/images/generations"
        method: "POST"
        price_type: "flat"
        price_sats: 500
        description: "DALL-E image generation"

      - path: "/v1/embeddings"
        method: "POST"
        price_type: "flat"
        price_sats: 20
        description: "Text embeddings"

      - path: "/v1/audio/speech"
        method: "POST"
        price_type: "flat"
        price_sats: 300
        description: "Text-to-speech"

      - path: "/v1/audio/transcriptions"
        method: "POST"
        price_type: "flat"
        price_sats: 200
        description: "Whisper transcription"
```

## Enforcement Rules

The proxy MUST enforce these before proxying to upstream:

### 1. Request body size limit

Before doing anything, check `Content-Length` or body size:

```python
if len(request_body_bytes) > endpoint.max_request_bytes:
    return 413, {"error": {"code": "request_too_large", "message": f"Request body exceeds {endpoint.max_request_bytes} bytes"}}
```

This bounds input token cost. 32KB of text ≈ 8,000 tokens worst case.

### 2. Output token cap

For `/v1/chat/completions`, before storing the request body for later proxying:

```python
body = json.loads(request_body)
model_name = body.get("model", "_default")
model_config = endpoint.models.get(model_name, endpoint.models["_default"])

# Force max_tokens to our cap
user_max = body.get("max_tokens") or body.get("max_completion_tokens")
our_cap = model_config["max_output_tokens"]

if user_max is None or user_max > our_cap:
    body["max_tokens"] = our_cap

# Remove max_completion_tokens if present (newer API field, same purpose)
body.pop("max_completion_tokens", None)

# Store the MODIFIED body, not the original
stored_body = json.dumps(body)
```

This ensures the upstream call never generates more output tokens than we've priced for.

### 3. Reject unknown models with _default pricing

If a model isn't in the config, use `_default`. If `_default` doesn't exist, return 400:

```python
if model_name not in endpoint.models and "_default" not in endpoint.models:
    return 400, {"error": {"code": "model_not_supported", "message": f"Model {model_name} is not supported"}}
```

### 4. Streaming support

When proxying, if the user's stored request body has `"stream": true`, the proxy should stream the upstream response back to the client. This is important for chat completions UX. The token cap still applies — OpenAI respects `max_tokens` regardless of streaming.

## Pricing Math (reference, not code)

Why these prices are safe at $100K/BTC (1 sat ≈ $0.001):

| Model | Our price | Worst case upstream cost | Our revenue | Margin |
|---|---|---|---|---|
| gpt-4o-mini | 50 sats ($0.05) | 8K in × $0.15/M + 2K out × $0.60/M = $0.002 | 25x |
| gpt-4.1-nano | 50 sats ($0.05) | 8K × $0.10/M + 2K × $0.40/M = $0.002 | 25x |
| gpt-4.1-mini | 100 sats ($0.10) | 8K × $0.40/M + 2K × $1.60/M = $0.006 | 16x |
| gpt-4o | 500 sats ($0.50) | 8K × $2.50/M + 2K × $10/M = $0.04 | 12x |
| gpt-4.1 | 500 sats ($0.50) | 8K × $2/M + 2K × $8/M = $0.032 | 15x |
| gpt-5-mini | 150 sats ($0.15) | 8K × $0.25/M + 2K × $2/M = $0.006 | 25x |
| gpt-5 | 600 sats ($0.60) | 8K × $1.25/M + 2K × $10/M = $0.03 | 20x |
| gpt-5.1 | 600 sats ($0.60) | 8K × $1.25/M + 2K × $10/M = $0.03 | 20x |
| gpt-5.2 | 800 sats ($0.80) | 8K × $1.75/M + 2K × $14/M = $0.042 | 19x |

Margins are 12-25x in the worst case. Most real requests use far fewer tokens.

If BTC drops 50% to $50K, margins halve — still 6-12x. Safe.

## /redeem endpoint change

Use preimage-only redemption:

```
GET /redeem?preimage={64_hex_chars}
```

Server computes `payment_hash = sha256(bytes.fromhex(preimage)).hex()` and uses that to look up the stored request. No payment_hash in the URL.

## /api/catalog endpoint

Return the full pricing catalog so users know what's available:

```json
{
  "apis": {
    "openai": {
      "name": "OpenAI",
      "endpoints": [
        {
          "path": "/v1/chat/completions",
          "description": "Chat completions",
          "price_type": "per_model",
          "models": {
            "gpt-4o-mini": {"price_sats": 50, "max_output_tokens": 2000},
            "gpt-4.1-nano": {"price_sats": 50, "max_output_tokens": 2000},
            "gpt-4.1-mini": {"price_sats": 100, "max_output_tokens": 2000},
            "gpt-4o": {"price_sats": 500, "max_output_tokens": 2000},
            "gpt-4.1": {"price_sats": 500, "max_output_tokens": 2000},
            "gpt-5-mini": {"price_sats": 150, "max_output_tokens": 2000},
            "gpt-5": {"price_sats": 600, "max_output_tokens": 2000},
            "gpt-5.1": {"price_sats": 600, "max_output_tokens": 2000},
            "gpt-5.2": {"price_sats": 800, "max_output_tokens": 2000}
          }
        },
        {
          "path": "/v1/images/generations",
          "description": "DALL-E image generation",
          "price_type": "flat",
          "price_sats": 500
        }
      ]
    }
  }
}
```
