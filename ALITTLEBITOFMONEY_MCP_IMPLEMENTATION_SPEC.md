# alittlebitofmoney-mcp: Research + Implementation Spec

Date: February 24, 2026 (US)

## 1) Objective
Build an MCP server named `alittlebitofmoney-mcp` that:

- Pulls and tracks `https://alittlebitofmoney.com/api/catalog`.
- Exposes a strategic toolbox (not a noisy 1:1 endpoint dump).
- Calls paid ALBOM API endpoints reliably with bearer auth.
- Updates tool definitions when catalog changes.

Primary user concern addressed: avoid too many overlapping tools while preserving coverage.

## 2) Research Findings

### 2.1 Live API Catalog Snapshot (verified)
Snapshot time: February 24, 2026, ~05:47 UTC from `/api/catalog`.

- APIs: 1 (`openai`)
- Endpoints: 11 total
- Per-model endpoints: 9
- Flat-priced endpoints: 2

Endpoints currently exposed:

1. `/v1/chat/completions` (per_model, 18 models)
2. `/v1/responses` (per_model, 18 models)
3. `/v1/images/generations` (per_model, 6 models)
4. `/v1/images/edits` (per_model, 5 models)
5. `/v1/images/variations` (flat)
6. `/v1/audio/speech` (per_model, 4 models)
7. `/v1/audio/transcriptions` (per_model, 4 models)
8. `/v1/audio/translations` (flat)
9. `/v1/embeddings` (per_model, 4 models)
10. `/v1/moderations` (per_model, 4 models)
11. `/v1/video/generations` (per_model, 3 models)

Observed overlap:

- Exact model-set duplicate cluster: `chat/completions` and `responses` (Jaccard 1.0).
- Near overlap: `images/generations` and `images/edits` model sets (Jaccard ~0.833), but different payload types and intent.

Conclusion: there is one clear consolidation candidate (`chat` vs `responses`), while most other endpoints are distinct enough to keep separate.

### 2.2 Payment/Auth Behavior (verified)

- Paid API calls without auth return HTTP `402` with:
  - `status: payment_required`
  - `invoice`, `payment_hash`, `amount_sats`, `expires_in`
  - headers include `WWW-Authenticate: L402 ...`, `X-Price-Sats`, `X-Topup-URL`
- Topup mode is enabled in production (`/health` shows `topup.ready=true`).
- Bearer token path is available (`Authorization: Bearer <token>`).

Implementation implication:

- MCP server should be bearer-first for normal tool execution.
- Do not intentionally create invoices during routine calls when token is missing.

### 2.3 MCP Protocol/SDK (current state)

Spec and docs indicate:

- Latest MCP spec revision is `2025-11-25`.
- Lifecycle requires `initialize` then `initialized` before normal traffic.
- Tools can signal dynamic changes via `notifications/tools/list_changed` (with `tools.listChanged` capability).
- Tool names are constrained (max length and allowed characters) and should be clear and unique.
- `ToolAnnotations` support `title`, `readOnlyHint`, `idempotentHint`, etc.
- Transport docs indicate `stdio` and `Streamable HTTP` as baseline transports for current spec.

SDK maturity page (published Feb 23, 2026) shows TypeScript SDK as Tier 1.

Recommendation: implement in TypeScript first unless there is a hard repo constraint otherwise.

## 3) Toolbox Strategy (the key decision)

Expose two profiles:

- `compact` (default): optimized for agent usability and low ambiguity.
- `full`: near 1:1 endpoint coverage for power users.

### 3.1 Compact Profile (recommended default)
Tools:

1. `albom_catalog_get`
2. `albom_text_generate` -> `/v1/responses`
3. `albom_image_generate` -> `/v1/images/generations`
4. `albom_image_edit` -> `/v1/images/edits`
5. `albom_audio_transcribe` -> `/v1/audio/transcriptions` (optional `translate_to_english` switch can route to `/v1/audio/translations`)
6. `albom_audio_speech` -> `/v1/audio/speech`
7. `albom_video_generate` -> `/v1/video/generations` (tagged expensive)
8. `albom_safety_moderate` -> `/v1/moderations` (optional include flag)
9. `albom_embedding_create` -> `/v1/embeddings` (optional include flag)

Consolidations in compact profile:

- Hide `chat/completions`; keep `responses` as canonical text generation surface.
- Fold `audio/translations` into `albom_audio_transcribe` via boolean mode.

### 3.2 Full Profile
Expose one tool per endpoint plus catalog utility:

- `albom_openai_chat_completions`
- `albom_openai_responses`
- `albom_openai_images_generations`
- `albom_openai_images_edits`
- `albom_openai_images_variations`
- `albom_openai_audio_speech`
- `albom_openai_audio_transcriptions`
- `albom_openai_audio_translations`
- `albom_openai_embeddings`
- `albom_openai_moderations`
- `albom_openai_video_generations`
- `albom_catalog_get`

Optional (off by default):

- `albom_raw_call` (strict allowlist against catalog paths).

### 3.3 Deterministic Dedup Rule
When generating tools from catalog:

1. Compute endpoint signature:
   - `method`
   - `content_type` (`json`/`multipart`)
   - argument-key set from `example` (minus cosmetic fields)
   - sorted model set hash (for per_model)
2. Candidate duplicate if:
   - same `method` and same `content_type`, and
   - model-set Jaccard >= `0.95`, and
   - path family is same (`/v1/chat/*` vs `/v1/responses` considered text-generation family).
3. Keep canonical endpoint by precedence table:
   - text: `responses` > `chat/completions`
   - image: keep both `generations` and `edits` (different intent)
   - audio: merge `translations` into transcription wrapper when profile is compact.

This gives predictable behavior and avoids accidental over-pruning.

## 4) Functional Specification

### 4.1 Configuration
Environment variables:

- `ALBOM_BASE_URL` (default `https://alittlebitofmoney.com`)
- `ALBOM_BEARER_TOKEN` (optional but strongly recommended)
- `ALBOM_TOOL_PROFILE` (`compact` default, `full` optional)
- `ALBOM_INCLUDE_MODERATION` (`true` default in full, `false` default in compact)
- `ALBOM_INCLUDE_EMBEDDINGS` (`true` default in full, `false` default in compact)
- `ALBOM_INCLUDE_VIDEO` (`true` default)
- `ALBOM_ALLOW_RAW_TOOL` (`false` default)
- `ALBOM_CATALOG_TTL_MS` (default `300000`)
- `ALBOM_HTTP_TIMEOUT_MS` (default `90000`)
- `ALBOM_MAX_RETRIES` (default `2` for 429/5xx)

### 4.2 Catalog Sync

On startup:

1. Fetch `/api/catalog`.
2. Validate expected shape (`apis`, `endpoints`, pricing fields).
3. Build internal `CatalogState` and derived `ToolState`.

During runtime:

1. Refresh every `ALBOM_CATALOG_TTL_MS`.
2. Recompute tool set.
3. If tool signatures changed, update registry and emit `notifications/tools/list_changed`.

### 4.3 Tool I/O Contract

All actionable tools should return structured payload:

```json
{
  "ok": true,
  "status": 200,
  "endpoint": "/v1/responses",
  "model": "gpt-4o-mini",
  "price_sats": 30,
  "data": { "...upstream response...": "..." }
}
```

Error shape:

```json
{
  "ok": false,
  "status": 402,
  "endpoint": "/v1/responses",
  "error": {
    "code": "payment_required",
    "message": "Bearer token missing or insufficient",
    "amount_sats": 30,
    "invoice": "lnbc...",
    "payment_hash": "...",
    "topup_url": "/topup"
  }
}
```

MCP response mapping:

- `structuredContent`: full machine-readable object above.
- `content[0].text`: short human summary.
- `isError=true` for non-2xx.

### 4.4 Auth/Payment Policy

- If `ALBOM_BEARER_TOKEN` is missing, tool call should fail fast locally with clear setup error by default.
- Optional mode `allow_l402_quote=true` can call without bearer to intentionally return invoice data (quote flow).
- Never auto-pay invoices in MCP server.

### 4.5 HTTP Routing Rule

Use `POST {ALBOM_BASE_URL}/openai{catalog_path}`.

Example:

- catalog path `/v1/responses` -> call `POST /openai/v1/responses`

(Proxy also accepts `/openai/responses` style via internal normalization, but use explicit `/v1/...` for clarity.)

### 4.6 Multipart Handling

For multipart tools accept either:

- `file_path` (preferred for local MCP host), or
- `file_base64` + `file_name` + `mime_type`.

Validation:

- exactly one of `file_path` or `file_base64`.
- enforce safe size limits before upload when known.

## 5) Suggested Tool Schemas (compact)

Minimal shape suggestions:

1. `albom_catalog_get` (`readOnlyHint=true`)
- input: `{ "refresh": boolean? }`
- returns current normalized catalog + derived summaries.

2. `albom_text_generate`
- input: `{ "model": "string", "input": "string|array", "instructions": "string?", "max_output_tokens": "number?", "temperature": "number?" }`
- routes to `/v1/responses`.

3. `albom_image_generate`
- input: `{ "model": "string", "prompt": "string", "size": "string?" }`

4. `albom_image_edit`
- input: `{ "model": "string", "prompt": "string", "image_file_path|image_file_base64": "..." }`

5. `albom_audio_transcribe`
- input: `{ "model": "string?", "audio_file_path|audio_file_base64": "...", "translate_to_english": "boolean?" }`
- route:
  - false -> `/v1/audio/transcriptions`
  - true -> `/v1/audio/translations`

6. `albom_audio_speech`
- input: `{ "model": "string", "voice": "string", "input": "string", "format": "string?" }`

7. `albom_video_generate`
- input: `{ "model": "string", "prompt": "string", "duration": "number?", "size": "string?" }`
- annotate as expensive in description.

8. `albom_safety_moderate` (optional in compact)
- input: `{ "model": "string?", "input": "string|array" }`

9. `albom_embedding_create` (optional in compact)
- input: `{ "model": "string?", "input": "string|array" }`

## 6) Technical Architecture

## 6.1 Modules

- `src/config.ts`: env parsing + defaults
- `src/catalog.ts`: fetch, validate, normalize, diff
- `src/dedup.ts`: profile builder + duplicate/merge logic
- `src/httpClient.ts`: outbound calls, retries, timeout, auth headers
- `src/tools/*.ts`: tool implementations
- `src/server.ts`: MCP server bootstrap + capabilities + transports
- `src/types.ts`: catalog/tool/result types

## 6.2 Internal Types (minimum)

- `CatalogState`
- `EndpointDescriptor`
- `ToolDescriptor`
- `ToolProfile` (`compact|full`)
- `AlbomToolResult<T>`

## 6.3 Transport

- Implement `stdio` first.
- Add Streamable HTTP transport if strict spec parity is required by host environment.

## 7) Error Handling Matrix

Map upstream -> MCP result consistently:

- 400 -> `isError=true`, code from upstream error body.
- 401 -> `invalid_token` or auth errors.
- 402 + `payment_required` -> include invoice metadata.
- 402 + `insufficient_balance` -> include required vs available sats if present.
- 404 -> endpoint missing (catalog stale or server changed).
- 413 -> request too large.
- 429/5xx -> retry policy then return normalized error.

## 8) Testing Plan

### 8.1 Unit

- Catalog shape validation.
- Dedup algorithm with fixture proving:
  - chat/responses collapse in compact mode.
  - image gen/edit remain separate.
  - audio transcription+translation merge behavior.

### 8.2 Integration (mock HTTP)

- Success path (200).
- `payment_required` path (402).
- `invalid_token` (401).
- multipart file path and base64 path.
- list-changed notification on simulated catalog change.

### 8.3 Optional Live Smoke (requires token)

- `albom_catalog_get`
- one cheap text request
- one moderation or embedding request

## 9) Rollout Plan

1. Implement compact profile only.
2. Ship and validate tool selection quality with real agent traces.
3. Enable full profile behind env flag.
4. Add periodic catalog sync + list_changed.
5. Add raw tool only if explicitly needed.

## 10) Acceptance Criteria

- MCP server starts and serves tools via stdio.
- `albom_catalog_get` returns live catalog and derived summary.
- Compact mode exposes consolidated toolset (no separate chat tool).
- Full mode exposes endpoint-level toolset.
- Toolset updates when catalog changes and sends list-changed notification.
- Errors are normalized and machine-readable.
- No invoice auto-payment behavior.

## 11) Open Decisions for the Implementing Repo

1. TypeScript vs Python runtime choice (TypeScript recommended from current maturity docs).
2. Whether to include Streamable HTTP in v1 or add in v1.1.
3. Whether moderation/embeddings are on by default in compact mode.
4. Whether to expose raw endpoint tool at all.

## Sources

- Catalog endpoint (live): [https://alittlebitofmoney.com/api/catalog](https://alittlebitofmoney.com/api/catalog)
- Health endpoint (live): [https://alittlebitofmoney.com/health](https://alittlebitofmoney.com/health)
- MCP lifecycle (2025-11-25): [https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)
- MCP transports (2025-11-25): [https://modelcontextprotocol.io/specification/2025-11-25/basic/transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
- MCP tools (2025-11-25): [https://modelcontextprotocol.io/specification/2025-11-25/server/tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)
- MCP schema reference (`ToolAnnotations`): [https://modelcontextprotocol.io/specification/2025-11-25/schema](https://modelcontextprotocol.io/specification/2025-11-25/schema)
- MCP SDK maturity levels: [https://modelcontextprotocol.io/docs/sdk](https://modelcontextprotocol.io/docs/sdk)
- TypeScript SDK repo: [https://github.com/modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk)
- Python SDK repo: [https://github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- Tool naming standardization note (SEP-986 context): [https://modelcontextprotocol.io/blog/mcp-updates-october-2025](https://modelcontextprotocol.io/blog/mcp-updates-october-2025)

