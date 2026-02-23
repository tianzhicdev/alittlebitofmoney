# Backend Spec — Codex

## Context

FastAPI server in `server.py`. Lightning-paid API proxy. Users POST a request, get a 402 with a Lightning invoice, pay it, then redeem with the preimage to get the upstream response. This spec covers request pre-validation and cleanup.

---

## 1. Request Pre-Validation (Critical)

**File:** `server.py`

**Problem:** Users can send malformed requests (missing required fields like `messages` for chat completions), pay the Lightning invoice, and then get an error from OpenAI on redeem. They paid for nothing. This will destroy trust with first users.

**Solution:** Validate that required fields exist in the request body BEFORE creating the invoice. Reject with a 400 error if required fields are missing. Only check field existence and basic type — let OpenAI handle deep validation.

**Implementation:**

Add a validation function:

```python
# Required fields per endpoint. Only check existence and basic type.
_REQUIRED_FIELDS: Dict[str, list] = {
    "/v1/chat/completions": [("messages", list)],
    "/v1/responses": [("input", (str, list))],
    "/v1/images/generations": [("prompt", str)],
    "/v1/images/edits": [],  # multipart — prompt is optional for edits
    "/v1/audio/speech": [("input", str), ("voice", str)],
    "/v1/embeddings": [("input", (str, list))],
    "/v1/moderations": [("input", (str, list))],
    "/v1/video/generations": [("prompt", str)],
}


def _validate_required_fields(
    normalized_path: str, request_body: Dict[str, Any]
) -> Optional[JSONResponse]:
    """Return an error response if required fields are missing, else None."""
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
                f"Field '{field_name}' must be {expected_type.__name__ if isinstance(expected_type, type) else ' or '.join(t.__name__ for t in expected_type)}",
            )
        # For lists (like messages), check non-empty
        if isinstance(value, list) and len(value) == 0:
            return _build_error(
                400,
                "invalid_field_value",
                f"Field '{field_name}' must not be empty",
            )
        # For strings, check non-empty
        if isinstance(value, str) and not value.strip():
            return _build_error(
                400,
                "invalid_field_value",
                f"Field '{field_name}' must not be empty",
            )

    return None
```

**Where to call it:** In the `create_payment_required` handler, after JSON parsing succeeds and after `_apply_request_rules`, but before `_price_for_request` and invoice creation:

```python
    # After line: request_body = _apply_request_rules(normalized_path, endpoint_config, request_body)
    # Add:
    validation_error = _validate_required_fields(normalized_path, request_body)
    if validation_error is not None:
        return validation_error
```

This ensures we never issue an invoice for a request that will definitely fail upstream.

**For multipart endpoints** (`/v1/audio/transcriptions`, `/v1/audio/translations`, `/v1/images/edits`, `/v1/images/variations`): These use form data, not JSON. The current code doesn't parse multipart fields before invoicing. For now, skip validation on multipart endpoints — the file presence is inherently validated by the upload itself. Add a comment noting this:

```python
    # Note: multipart endpoints (audio/transcriptions, audio/translations,
    # images/edits, images/variations) are not pre-validated because the
    # request body is raw multipart form data, not parsed JSON.
```

---

## 2. Delete Orphaned File

**File to delete:** `public/doc.html`

This is a leftover from the pre-React frontend. Delete the file. If the `public/` directory at the project root is now empty, delete the directory too.

**Note:** The React frontend lives in `frontend/`. The root-level `public/` directory is not used by anything. The server's `_resolve_frontend_file` function only looks in `frontend/dist/`.

---

## 3. Add robots.txt and sitemap.xml Serving

**File:** `server.py`

The React frontend build will include `robots.txt` and `sitemap.xml` in `frontend/dist/` (placed there via `frontend/public/`). The existing `frontend_catchall` handler already serves static files from `frontend/dist/`, so these will be served automatically at:
- `https://alittlebitofmoney.com/robots.txt`
- `https://alittlebitofmoney.com/sitemap.xml`

**Verify this works:** After the frontend is rebuilt with the new files, confirm:
```bash
curl -s https://alittlebitofmoney.com/robots.txt
curl -s https://alittlebitofmoney.com/sitemap.xml
```

No backend code change needed — the catch-all handler already resolves static files before falling back to the SPA index. Just verify it works after deploy.

---

## 4. Google Search Console Preparation

No code changes needed. After deploy, the site owner should:

1. Go to https://search.google.com/search-console
2. Add property: `https://alittlebitofmoney.com`
3. Verify via DNS TXT record (Cloudflare DNS panel) or HTML file upload
4. Submit sitemap: `https://alittlebitofmoney.com/sitemap.xml`
5. Request indexing for the 3 main URLs

This is a manual step, not a code task.

---

## Summary Checklist

- [ ] Add `_REQUIRED_FIELDS` dict and `_validate_required_fields()` function to `server.py`
- [ ] Call validation in `create_payment_required` after JSON parsing, before invoice creation
- [ ] Delete `public/doc.html` and root `public/` directory if empty
- [ ] Verify robots.txt and sitemap.xml are served correctly after frontend rebuild
- [ ] (Manual) Set up Google Search Console and submit sitemap

---

## Testing

After implementing pre-validation, run these tests:

```bash
# Should return 400 with "missing_required_field", NOT a 402 invoice
curl -s -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini"}' | jq .

# Should return 400 — empty messages array
curl -s -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[]}' | jq .

# Should return 402 with invoice — valid request
curl -s -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}' | jq .

# Should return 400 — missing prompt
curl -s -X POST https://alittlebitofmoney.com/openai/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{"model":"dall-e-3"}' | jq .

# Should return 400 — missing input and voice
curl -s -X POST https://alittlebitofmoney.com/openai/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model":"tts-1"}' | jq .
```
