import CodeTabs from '../components/CodeTabs';
import FAQ from '../components/FAQ';
import FlowDiagram from '../components/FlowDiagram';
import GlassCard from '../components/GlassCard';
import WalletTabs from '../components/WalletTabs';
import CodeBlock from '../components/CodeBlock';
import { useReveal } from '../hooks/useReveal';

const RESPONSE_SHAPE = `{
  "status": "payment_required",
  "invoice": "lnbc...",
  "payment_hash": "abc123...",
  "amount_sats": 30,
  "expires_in": 600
}`;

const QUICK_START = `PHOENIX_WALLET_PASSWORD=your-phoenix-password
# Step 1: Request -> 402 + invoice
INVOICE=$(curl -sS -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello bitcoin world"}]}' | jq -r '.invoice')
# Step 2: Pay (replace with your wallet integration)
PREIMAGE=$(curl -sS -X POST http://localhost:9741/payinvoice  -u ":$PHOENIX_WALLET_PASSWORD" --data-urlencode "invoice=$INVOICE" | jq -r '.paymentPreimage')
# Step 3: Redeem
curl -sS "https://alittlebitofmoney.com/redeem?preimage=$PREIMAGE" | jq -r '.choices[0].message.content'
Hello! How can I assist you in the Bitcoin world today?`;

const AUTOMATION_TABS = [
  {
    label: 'python',
    language: 'python',
    code: `import requests

API = "https://alittlebitofmoney.com"

# Step 1: Request -> 402 + invoice
step1 = requests.post(f"{API}/openai/v1/chat/completions", json={
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "Say hello"}],
})
data = step1.json()
invoice = data["invoice"]

# Step 2: Pay (replace with your wallet integration)
preimage = pay_invoice(invoice)  # <- see wallet integrations below

# Step 3: Redeem
result = requests.get(f"{API}/redeem", params={"preimage": preimage})
print(result.json())`,
  },
  {
    label: 'javascript',
    language: 'javascript',
    code: `const API = "https://alittlebitofmoney.com";

// Step 1: Request -> 402 + invoice
const step1 = await fetch(API + "/openai/v1/chat/completions", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "Say hello" }],
  }),
});
const { invoice } = await step1.json();

// Step 2: Pay (replace with your wallet integration)
const preimage = await payInvoice(invoice); // <- see wallet integrations below

// Step 3: Redeem
const result = await fetch(API + "/redeem?preimage=" + preimage);
console.log(await result.json());`,
  },
];

const FAQ_ITEMS = [
  {
    question: 'What happens if I pay but do not redeem?',
    answer:
      'Preimage redemption is valid for 10 minutes after invoice creation. After that, payment is non-refundable.',
  },
  {
    question: "What's the preimage?",
    answer: 'Cryptographic proof of payment. Verify sha256(preimage) == payment_hash.',
  },
  {
    question: 'Can I use this from any country?',
    answer: 'If you can send a Lightning payment, yes.',
  },
  {
    question: 'Is this affiliated with OpenAI?',
    answer: 'No. This is an independent proxy service.',
  },
  {
    question: 'What if OpenAI is down?',
    answer: 'You receive an upstream error response. Payment is non-refundable once paid.',
  },
  {
    question: 'Why not use OpenAI directly?',
    answer: 'You can, if you have access and are in a supported region.',
  },
  {
    question: 'Do you store my prompts?',
    answer: 'Requests are held in memory until redeemed (max 10 minutes), then deleted.',
  },
  {
    question: 'Is there a rate limit?',
    answer: 'Upstream rate limits apply and are passed through.',
  },
];

export default function Doc() {
  const revealRef = useReveal();

  return (
    <div ref={revealRef} className="flex flex-col gap-5">
      <section className="hero-panel reveal" style={{ minHeight: '48vh' }}>
        <div className="hero-content">
          <p className="eyebrow">Developer Guide</p>
          <h1 className="glow-title">Lightning Payment Flow</h1>
          <p className="hero-sub">Send request, pay the invoice, redeem with preimage.</p>
        </div>
      </section>

      <section className="section reveal">
        <h2 className="section-title">Flow Diagram</h2>
        <FlowDiagram detailed />
      </section>

      <section className="section reveal">
        <h2 className="section-title">Quick Start</h2>
        <p className="section-intro">
          Try it from your terminal right now. Pay the invoice with any Lightning wallet on your phone.
        </p>
        <CodeBlock
          language="bash"
          code={QUICK_START}
        />
      </section>

      <section className="section reveal">
        <h2 className="section-title">Wallet Integrations</h2>
        <p className="section-intro">Implement pay_invoice() per wallet and plug it into the flow.</p>
        <WalletTabs />
      </section>

      <section className="section reveal">
        <div className="preimage-callout">
          <strong>Browser apps: use WebLN.</strong> If users have Alby or another WebLN extension,
          <span className="inline-code"> window.webln.sendPayment(invoice)</span> returns preimage directly.
        </div>
      </section>

      <section className="section reveal">
        <h2 className="section-title">FAQ</h2>
        <FAQ items={FAQ_ITEMS} />
      </section>

      <section className="section reveal" id="api-policy">
        <h2 className="section-title">Policy</h2>
        <GlassCard>
          <p className="text-[#95b9cd]">
            Access is pay-per-request. Pricing and endpoint availability may change. Abusive usage may be blocked.
          </p>
        </GlassCard>
      </section>

      <section className="section reveal" id="terms">
        <h2 className="section-title">Terms</h2>
        <GlassCard>
          <p className="text-[#95b9cd]">
            Service is provided as-is. You are responsible for wallet credentials, invoice handling, and upstream API
            usage.
          </p>
        </GlassCard>
      </section>
    </div>
  );
}
