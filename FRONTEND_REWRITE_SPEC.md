# Frontend Rewrite Spec: Vite + React

## Goal

Rewrite the `public/` HTML frontend as a Vite + React SPA. Keep the exact same visual theme (dark terminal aesthetic, glassmorphic cards, GSAP reveals). Three routes: `/` (home), `/catalog` (pricing + examples), `/doc` (flow + wallet guide). The `/doc` page is the most important page on the site.

---

## Tech Stack

- **Vite** — build tool
- **React** — UI (functional components, hooks only)
- **React Router** — client-side routing (3 routes)
- **Tailwind CSS** — utility classes for layout, PLUS a `theme.css` file for the custom glass/glow effects that Tailwind can't express
- **GSAP + ScrollTrigger** — scroll reveal animations (CDN import, same as current)
- **No other deps.** No state lib, no UI component lib, no styled-components.

---

## Project Structure

```
frontend/
  public/
    favicon.svg                  # copy from current public/assets/
  src/
    theme.css                    # CSS variables, background, glass effects, animations
    main.jsx                     # ReactDOM.createRoot + BrowserRouter
    App.jsx                      # Layout shell (Navbar, Outlet, Footer)
    hooks/
      useCatalog.js              # fetch /api/catalog, expose satsToDisplay(sats)
      useReveal.js               # GSAP ScrollTrigger hook for section refs
    components/
      Navbar.jsx                 # sticky nav, brand, route links
      Footer.jsx                 # links, version, year
      CodeBlock.jsx              # reusable: code + copy button
      CodeTabs.jsx               # reusable: tabbed CodeBlocks (lang tabs)
      GlassCard.jsx              # reusable: bordered card with backdrop blur
      FlowDiagram.jsx            # 3-step request→pay→redeem visual
      ModelTable.jsx             # pricing table for per_model endpoints
      WalletTabs.jsx             # tabbed wallet integration code
    pages/
      Home.jsx                   # landing page
      Catalog.jsx                # pricing + per-endpoint code examples
      Doc.jsx                    # flow diagram, code examples, wallet guide
  index.html
  vite.config.js
  tailwind.config.js
  postcss.config.js
  package.json
```

---

## Build & Deploy

```bash
cd frontend
npm install
npm run build            # → frontend/dist/
```

Deploy script copies `dist/*` to the VPS static dir. Nginx serves static files and proxies API routes. Same nginx config as current — just point root at the built output.

Update `deploy.sh` to add a build step before rsync:

```bash
# In deploy_prod, before rsync:
if [[ -d "frontend" ]]; then
  cd frontend && npm ci && npm run build && cd ..
fi
```

And update rsync excludes to include `frontend/node_modules`.

The built `dist/` folder replaces `public/`. Remove `public/` from the repo after migration.

---

## Design System & Color Rules

### Document this in the codebase as a comment block at the top of `theme.css`:

```css
/*
 * COLOR RULES — alittlebitofmoney design system
 *
 * Bitcoin / sats / Lightning → ORANGE (#f7931a / var(--accent))
 *   - Sat prices, "sats" label, Lightning references, CTA buttons
 *   - Active tab indicators, bitcoin pills, copy buttons
 *   - Sats column in pricing tables
 *
 * USD / fiat → MUTED (#8ab1c6 / var(--muted))
 *   - USD column in pricing tables, secondary price display
 *   - Never use orange for USD amounts
 *
 * Code / endpoints / tech → CYAN (#9ad8ef / var(--text) family)
 *   - Inline code, endpoint paths, model names, code blocks
 *
 * Background → DARK NAVY (--bg-0 through --bg-2)
 *   - Glass cards, code cards use semi-transparent navy
 *
 * USD DISPLAY FORMAT:
 *   - Under $1.00 → show as cents: "2.0¢", "13.0¢"
 *   - $1.00 and above → show as dollars: "$1.20", "$3.60"
 *   - Always prefix with "~" since it's a BTC conversion estimate
 *
 * FONT RULES:
 *   - Body text: Space Grotesk
 *   - Code, monospace, labels: JetBrains Mono
 */
```

### CSS Variables (keep from current `styles.css`):

```css
:root {
  --bg-0: #060b11;
  --bg-1: #0b1119;
  --bg-2: #121a24;
  --text: #b7e9ff;
  --muted: #8ab1c6;
  --accent: #f7931a;          /* Bitcoin orange — THE brand color for sats */
  --accent-soft: rgba(247, 147, 26, 0.18);
  --cyan-soft: rgba(46, 178, 255, 0.2);
  --glass-bg: rgba(11, 21, 32, 0.55);
  --glass-border: rgba(136, 202, 255, 0.28);
  --glass-shadow: 0 18px 40px rgba(0, 0, 0, 0.38);
  --content-width: 1140px;
  --radius-lg: 22px;
  --radius-md: 14px;
}
```

Note: the current site uses `--accent: #ff8c2a`. Change to `#f7931a` (the actual Bitcoin orange). Close enough visually, but correct.

---

## useCatalog Hook

```javascript
import { useState, useEffect } from 'react';

export function useCatalog() {
  const [catalog, setCatalog] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetch('/api/catalog')
      .then(r => {
        if (!r.ok) throw new Error('Catalog fetch failed');
        return r.json();
      })
      .then(data => { setCatalog(data); setLoading(false); })
      .catch(err => { setError(err); setLoading(false); });
  }, []);

  // Format sats to USD display string
  // Under $1 → "~2.0¢"   |   $1+ → "~$1.20"
  const satsToDisplay = (sats) => {
    if (!catalog?.btc_usd) return null;
    const usdCents = sats * catalog.btc_usd / 100_000_000 * 100;
    if (usdCents < 100) {
      return `~${usdCents.toFixed(1)}¢`;
    }
    return `~$${(usdCents / 100).toFixed(2)}`;
  };

  return { catalog, loading, error, satsToDisplay };
}
```

---

## Config Changes: Request Examples in config.yaml

Currently, request examples are hardcoded in `app.js` (`sampleJsonBody()`, `multipartSnippetConfig()`). Move them into `config.yaml` so they're served via `/api/catalog` and the frontend just renders what the API gives it.

### Add to each endpoint in config.yaml:

```yaml
- path: "/v1/chat/completions"
  method: POST
  description: "Chat completions (text, vision, structured output)"
  price_type: per_model
  example:
    content_type: json
    body:
      model: "gpt-4o-mini"
      messages:
        - role: "user"
          content: "Say hello in five words."

- path: "/v1/audio/transcriptions"
  method: POST
  description: "Transcribe audio to text (Whisper, GPT-4o)"
  price_type: per_model
  example:
    content_type: multipart
    fields:
      model: "whisper-1"
      file: "@sample.mp3"
    file_field: "file"
    file_name: "sample.mp3"
    file_comment: "audio file (mp3, wav, m4a, etc.)"

- path: "/v1/images/edits"
  method: POST
  description: "Edit images (inpainting, outpainting)"
  price_type: per_model
  example:
    content_type: multipart
    fields:
      model: "gpt-image-1"
      image: "@image.png"
      prompt: "Add lightning bolts to the background"
    file_field: "image"
    file_name: "image.png"
    file_comment: "image file (png)"
```

### Backend change in server.py `_build_catalog()`:

Include `example` in the endpoint dict passed to the frontend. Strip it from the internal config used for pricing — it's display-only.

```python
# In _build_catalog, when building each endpoint item:
if endpoint.get("example"):
    item["example"] = endpoint["example"]
```

### Full example list for all endpoints:

| Endpoint | content_type | Example body |
|---|---|---|
| `/v1/chat/completions` | json | `{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Say hello in five words."}]}` |
| `/v1/responses` | json | `{"model":"gpt-4o-mini","input":"Explain Bitcoin Lightning in one sentence."}` |
| `/v1/images/generations` | json | `{"model":"gpt-image-1-mini","prompt":"A neon bitcoin logo over brushed steel.","size":"1024x1024"}` |
| `/v1/audio/speech` | json | `{"model":"tts-1","voice":"alloy","input":"Hello from the Lightning Network."}` |
| `/v1/embeddings` | json | `{"model":"text-embedding-3-small","input":"Lightning invoices and preimages"}` |
| `/v1/moderations` | json | `{"model":"omni-moderation-latest","input":"This is a test message for content moderation."}` |
| `/v1/video/generations` | json | `{"model":"sora-2","prompt":"A golden bitcoin spinning slowly against a starry night sky."}` |
| `/v1/audio/transcriptions` | multipart | file=@sample.mp3, model=whisper-1 |
| `/v1/audio/translations` | multipart | file=@sample.mp3, model=whisper-1 |
| `/v1/images/edits` | multipart | image=@image.png, model=gpt-image-1, prompt="Add lightning bolts to the background" |
| `/v1/images/variations` | multipart | image=@image.png, model=dall-e-2 |

---

## Code Snippet Generation (frontend utility)

Create `src/utils/snippets.js` that takes an endpoint's `example` config and generates curl/python/javascript code. This replaces the massive `buildEndpointSnippets()` in current `app.js`.

```javascript
// src/utils/snippets.js

export function generateSnippets(apiName, endpointPath, example) {
  const route = `/${apiName}${endpointPath}`;

  if (example.content_type === 'multipart') {
    return generateMultipartSnippets(route, example);
  }
  return generateJsonSnippets(route, example);
}

function generateJsonSnippets(route, example) {
  const compact = JSON.stringify(example.body);
  const pretty = JSON.stringify(example.body, null, 2);

  return {
    curl: `API="https://alittlebitofmoney.com"

STEP1=$(curl -s -X POST "$API${route}" \\
  -H "Content-Type: application/json" \\
  -d '${compact}')

INVOICE=$(echo "$STEP1" | jq -r '.invoice')
echo "Pay this invoice with your wallet:"
echo "$INVOICE"

read -r -p "Preimage: " PREIMAGE
curl -s "$API/redeem?preimage=$PREIMAGE" | jq .`,

    python: `import requests

API = "https://alittlebitofmoney.com"

# Step 1: Send request → get 402 + invoice
step1 = requests.post(f"{API}${route}", json=${pretty})
invoice = step1.json()["invoice"]
print("Pay this invoice with your wallet:")
print(invoice)

# Step 2: Pay with your wallet, paste preimage
preimage = input("Preimage: ").strip()

# Step 3: Redeem
result = requests.get(f"{API}/redeem", params={"preimage": preimage})
print(result.json())`,

    javascript: `const API = "https://alittlebitofmoney.com";

// Step 1: Send request → get 402 + invoice
const step1 = await fetch(\`\${API}${route}\`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(${pretty}),
});

const { invoice } = await step1.json();
console.log("Pay this invoice with your wallet:", invoice);

// Step 2: Pay with your wallet, get preimage
const preimage = prompt("Preimage:");

// Step 3: Redeem
const result = await fetch(\`\${API}/redeem?preimage=\${preimage}\`);
console.log(await result.json());`
  };
}

// Similar for multipart — generate curl -F, requests with files={}, FormData
```

---

## Pages

### 1. Home (`/`)

Keep it simple and punchy. Same structure as current but cleaner.

**Sections:**
1. **Hero** — "Pay for APIs with Bitcoin. No signup. No API key." + inline curl example showing the 402 response
2. **How It Works** — `<FlowDiagram />` component (3 steps: Request → Pay → Redeem)
3. **Value Props** — 3 glass cards: "402 First", "Proof-Based Redeem", "Low Friction" (same as current)

**Removed:** nothing, this page is fine as-is.

### 2. Catalog (`/catalog`)

The pricing reference. Fetches `/api/catalog` and renders everything dynamically.

**Sections:**
1. **Header** — "API Catalog" + BTC/USD rate display (orange for BTC price, muted for "updated X min ago")
2. **Endpoint Cards** — one card per endpoint, each containing:
   - Endpoint method + full path (e.g. `POST /openai/v1/chat/completions`)
   - Description text
   - **Pricing**: `<ModelTable />` for per_model, flat price badge for flat
   - **Code Examples**: `<CodeTabs />` with curl / python / javascript tabs
     - Generated from the `example` field in the catalog response
     - Shows the full 3-step flow (request → pay → redeem)

**USD formatting in ModelTable:**

```jsx
function PriceCell({ sats, satsToDisplay }) {
  const usd = satsToDisplay(sats);
  return (
    <td>
      <span className="text-[var(--accent)] font-bold">{sats} sats</span>
      {usd && <span className="text-[var(--muted)] ml-2 text-sm">{usd}</span>}
    </td>
  );
}
```

Sats in orange. USD in muted gray. Under $1 shows cents, over $1 shows dollars.

### 3. Doc (`/doc`) — THE MOST IMPORTANT PAGE

This is where developers learn how to integrate. It needs to be comprehensive, visual, and copy-paste ready.

**Sections (in order):**

#### 3a. Hero
- "Lightning Payment Flow"
- "Send request, pay the invoice, redeem with preimage."

#### 3b. Flow Diagram (`<FlowDiagram />` — detailed version)
Visual 3-step diagram. Each step has:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   1. REQUEST     │────▶│    2. PAY        │────▶│   3. REDEEM      │
│                  │     │                  │     │                  │
│ POST /openai/... │     │ Pay BOLT11       │     │ GET /redeem?     │
│ → 402 + invoice  │     │ invoice with     │     │ preimage=...     │
│ + payment_hash   │     │ any LN wallet    │     │ → upstream       │
│                  │     │ → get preimage   │     │   response       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

Below the diagram, a callout box:

> **What's a preimage?** Every Lightning invoice has a `payment_hash`. When you pay, the Lightning Network reveals the `preimage` — a 64-character hex string. Only the payer receives it. Verify: `sha256(preimage) == payment_hash`. No accounts, no API keys — the preimage IS your receipt.

#### 3c. Core Routes Reference
Compact glass card:
- `POST /{api_name}/{endpoint}` → returns `402` with `invoice`, `payment_hash`, `amount_sats`, `expires_in`
- `GET /redeem?preimage={64_hex}` → returns upstream API response
- `GET /api/catalog` → returns available APIs, models, and pricing

Show the 402 response JSON shape:
```json
{
  "status": "payment_required",
  "invoice": "lnbc...",
  "payment_hash": "abc123...",
  "amount_sats": 30,
  "expires_in": 600
}
```

#### 3d. Quick Start (Manual Flow)
The "try it right now" section. One curl command, pay with phone, paste preimage.

```bash
# 1. Send request
curl -s -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello"}]}' | jq .

# 2. Copy the invoice, pay with your wallet (Phoenix, Muun, Zeus, Breez, etc.)
# 3. Paste the preimage from your wallet's payment details

curl -s "https://alittlebitofmoney.com/redeem?preimage=YOUR_PREIMAGE_HERE" | jq .
```

#### 3e. Automated Integration — Language Tabs
Full automated 3-step pattern in **curl**, **Python**, **JavaScript**. Use `<CodeTabs />`.

These show the pattern with a `pay_invoice()` placeholder:

**Python:**
```python
import requests

API = "https://alittlebitofmoney.com"

# Step 1: Request → 402 + invoice
step1 = requests.post(f"{API}/openai/v1/chat/completions", json={
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}],
})
data = step1.json()
invoice = data["invoice"]

# Step 2: Pay (replace with your wallet integration)
preimage = pay_invoice(invoice)  # ← see wallet integrations below

# Step 3: Redeem
result = requests.get(f"{API}/redeem", params={"preimage": preimage})
print(result.json())
```

**JavaScript:**
```javascript
const API = "https://alittlebitofmoney.com";

// Step 1: Request → 402 + invoice
const step1 = await fetch(`${API}/openai/v1/chat/completions`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "Say hello" }],
  }),
});
const { invoice } = await step1.json();

// Step 2: Pay (replace with your wallet integration)
const preimage = await payInvoice(invoice); // ← see wallet integrations below

// Step 3: Redeem
const result = await fetch(`${API}/redeem?preimage=${preimage}`);
console.log(await result.json());
```

#### 3f. Wallet Integrations (`<WalletTabs />`) — THE KEY SECTION

Tabbed section showing how to implement `pay_invoice()` for each wallet. Each wallet tab has sub-tabs for Python / JavaScript / bash.

**Wallet tabs:**

**Tab 1: Phoenixd** (self-custodial, easiest for servers)
```python
# Python
import requests, time

def pay_invoice(bolt11):
    resp = requests.post("http://localhost:9740/payinvoice", 
        data={"invoice": bolt11},
        auth=("", "your-phoenixd-password"))
    # Phoenix returns preimage directly
    return resp.json()["paymentPreimage"]
```
```javascript
// JavaScript
async function payInvoice(bolt11) {
  const resp = await fetch("http://localhost:9740/payinvoice", {
    method: "POST",
    headers: {
      "Authorization": "Basic " + btoa(":your-phoenixd-password"),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: `invoice=${bolt11}`,
  });
  const { paymentPreimage } = await resp.json();
  return paymentPreimage;
}
```
```bash
# bash
pay_invoice() {
  curl -s -u ":$PHOENIX_PASSWORD" \
    -d "invoice=$1" \
    http://localhost:9740/payinvoice | jq -r '.paymentPreimage'
}
```

**Tab 2: LND** (most popular node software)
```python
# Python
import requests, base64

def pay_invoice(bolt11):
    resp = requests.post("https://localhost:8080/v1/channels/transactions",
        json={"payment_request": bolt11},
        headers={"Grpc-Metadata-macaroon": MACAROON_HEX},
        verify=False)
    # LND returns base64 preimage, convert to hex
    b64_preimage = resp.json()["payment_preimage"]
    return base64.b64decode(b64_preimage).hex()
```
```javascript
// JavaScript  
async function payInvoice(bolt11) {
  const resp = await fetch("https://localhost:8080/v1/channels/transactions", {
    method: "POST",
    headers: { "Grpc-Metadata-macaroon": MACAROON_HEX },
    body: JSON.stringify({ payment_request: bolt11 }),
  });
  const { payment_preimage } = await resp.json();
  // base64 → hex
  return [...atob(payment_preimage)].map(c =>
    c.charCodeAt(0).toString(16).padStart(2, '0')).join('');
}
```

**Tab 3: Core Lightning (CLN)**
```python
# Python — via lightning-cli
import subprocess, json

def pay_invoice(bolt11):
    result = subprocess.run(
        ["lightning-cli", "pay", bolt11],
        capture_output=True, text=True)
    return json.loads(result.stdout)["payment_preimage"]
```
```bash
# bash
pay_invoice() {
  lightning-cli pay "$1" | jq -r '.payment_preimage'
}
```

**Tab 4: LNbits** (lightweight, hosted or self-hosted)
```python
# Python
import requests

def pay_invoice(bolt11):
    # Step 1: Pay
    resp = requests.post("https://your-lnbits/api/v1/payments",
        json={"out": True, "bolt11": bolt11},
        headers={"X-Api-Key": LNBITS_ADMIN_KEY})
    payment_hash = resp.json()["payment_hash"]
    # Step 2: Fetch preimage from payment details
    detail = requests.get(f"https://your-lnbits/api/v1/payments/{payment_hash}",
        headers={"X-Api-Key": LNBITS_ADMIN_KEY})
    return detail.json()["details"]["preimage"]
```

**Tab 5: Alby** (browser extension + API)
```javascript
// JavaScript — Browser (WebLN)
async function payInvoice(bolt11) {
  if (!window.webln) throw new Error("Install Alby extension");
  await window.webln.enable();
  const { preimage } = await window.webln.sendPayment(bolt11);
  return preimage;
}
```
```python
# Python — Alby Hub API
import requests

def pay_invoice(bolt11):
    resp = requests.post("https://api.getalby.com/payments/bolt11",
        json={"invoice": bolt11},
        headers={"Authorization": f"Bearer {ALBY_TOKEN}"})
    return resp.json()["payment_preimage"]
```

**Tab 6: Strike** (USD-denominated, no Bitcoin needed)
```python
# Python
import requests

def pay_invoice(bolt11):
    # Create payment quote
    quote = requests.post("https://api.strike.me/v1/payment-quotes/lightning",
        json={"lnInvoice": bolt11, "sourceCurrency": "USD"},
        headers={"Authorization": f"Bearer {STRIKE_API_KEY}"})
    quote_id = quote.json()["paymentQuoteId"]
    # Execute payment
    resp = requests.patch(f"https://api.strike.me/v1/payment-quotes/{quote_id}/execute",
        headers={"Authorization": f"Bearer {STRIKE_API_KEY}"})
    return resp.json()["preimage"]
```

#### 3g. WebLN Callout
Separate highlighted box:

> **Browser apps: Use WebLN.** If your users have Alby or another WebLN-compatible extension, the entire flow is 3 function calls — no backend wallet code needed. `window.webln.sendPayment(invoice)` returns the preimage directly.

#### 3h. FAQ (accordion)
- "What happens if I pay but don't redeem?" → Preimage is valid for 10 minutes after invoice creation. After that, payment is non-refundable.
- "What's the preimage?" → Cryptographic proof of payment. sha256(preimage) == payment_hash.
- "Can I use this from any country?" → If you can send a Lightning payment, yes.
- "Is this affiliated with OpenAI?" → No. Independent proxy.
- "What if OpenAI is down?" → You get an error response. Payment is non-refundable.
- "Why not just use OpenAI directly?" → You can if you have a credit card and live in a supported country.
- "Do you store my prompts?" → Requests held in memory until redeemed (max 10 min), then deleted.
- "Is there a rate limit?" → We pass through upstream rate limits.

#### 3i. Policy & Terms
Same as current but in the same page (no separate sections needed, just anchor IDs).

**REMOVED from /doc:** "Available API Categories" section (the 6 glass cards for Chat, Images, Video, Audio, Embeddings, Moderation). Useless — the catalog page shows this with actual pricing.

---

## Reusable Components

### `<CodeBlock code={string} language={string} />`
- Renders `<pre><code>` with copy button
- Monospace font, dark code card styling
- Copy button in orange accent

### `<CodeTabs tabs={[{label, code, language}]} />`
- Renders tab bar + CodeBlock panels
- Active tab in orange, inactive in muted
- Tabs: typically "curl", "python", "javascript"

### `<WalletTabs />`
- Outer tabs: wallet names (Phoenixd, LND, CLN, LNbits, Alby, Strike)
- Inner tabs per wallet: python, javascript, bash (where applicable)
- Each shows the `pay_invoice()` implementation

### `<FlowDiagram />`
- Three connected cards: Request → Pay → Redeem
- Arrows between them (CSS or SVG, not images)
- Each card has a step number, title, and 2-3 lines of detail
- Below: preimage explanation callout

### `<ModelTable endpoint={object} satsToDisplay={fn} />`
- Renders the model pricing table from catalog data
- Sats column in orange, USD column in muted
- USD uses the `satsToDisplay()` function (cents < $1, dollars >= $1)
- Hides `_default` row or shows it as "other models"

### `<GlassCard>`
- Wrapper component applying glass styling
- `border: 1px solid var(--glass-border)`, backdrop blur, shadow

### `<FAQ items={[{question, answer}]} />`
- Accordion — click to expand
- Simple state toggle per item

---

## Styling Approach

Use Tailwind for layout (flex, grid, padding, margin, responsive breakpoints). Use `theme.css` for the custom effects that require CSS variables, gradients, and animations:

**In theme.css (migrated from current styles.css):**
- CSS custom properties (`:root` vars)
- Body background (radial gradients + grid overlay + vignette)
- `.glass-card` styles (backdrop-filter, border, shadow)
- `.code-card` styles
- `.glow-title` animation
- `.model-table` styling (orange sats column, hover states)
- GSAP `.reveal` initial state
- Page transition animation
- All the current visual identity

**In Tailwind:**
- Layout: `flex`, `grid`, `gap-4`, `max-w-5xl`, `mx-auto`
- Spacing: `p-4`, `mt-8`, `mb-2`
- Responsive: `md:grid-cols-3`, `sm:grid-cols-1`
- Typography sizing: `text-sm`, `text-lg`

This split means the agent can use Tailwind for boring layout stuff while preserving the exact visual identity from the current CSS.

---

## What NOT to Build

- No dark/light mode toggle. Dark only.
- No cookie banner. No cookies.
- No analytics.
- No signup/login/auth. No accounts exist.
- No interactive playground or "try it live" widget. The curl command IS the playground.
- No blog, about page, or team page.
- No loading spinners or skeleton screens beyond a simple "Loading..." text.
- No syntax highlighting library. Plain monospace text is fine.

---

## Gitignore Fix

**CRITICAL:** Remove `lib/` from `.gitignore`. The `lib/invoice_store.py` and `lib/phoenix.py` modules need to be in the repo. Currently nobody can clone and run the project because these files are excluded. Add `frontend/node_modules/` to gitignore instead.

```diff
- lib/
+ frontend/node_modules/
+ frontend/dist/
```

---

## Migration Checklist

1. [ ] Fix `.gitignore` — remove `lib/`, add `frontend/node_modules/`, `frontend/dist/`
2. [ ] Commit `lib/invoice_store.py` and `lib/phoenix.py` to repo
3. [ ] Add `example` field to each endpoint in `config.yaml`
4. [ ] Update `_build_catalog()` in `server.py` to include `example` in response
5. [ ] Create `frontend/` with Vite + React + Tailwind
6. [ ] Migrate CSS theme from `public/assets/styles.css` to `frontend/src/theme.css`
7. [ ] Build all components and pages
8. [ ] Update `deploy.sh` to build frontend before rsync
9. [ ] Update nginx to serve from new static dir
10. [ ] Test all 3 pages render correctly
11. [ ] Test catalog fetches live data and formats USD correctly
12. [ ] Remove `public/` directory from repo
13. [ ] Update README with new dev workflow (`cd frontend && npm run dev`)
