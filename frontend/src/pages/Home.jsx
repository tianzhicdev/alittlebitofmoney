import { Link } from 'react-router-dom';
import FlowDiagram from '../components/FlowDiagram';
import GlassCard from '../components/GlassCard';
import CodeBlock from '../components/CodeBlock';
import { useReveal } from '../hooks/useReveal';

const HERO_CURL = `curl -s -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"Say hello in five words."}]}' | jq .

# => {
#   "status": "payment_required",
#   "invoice": "lnbc...",
#   "payment_hash": "abc123...",
#   "amount_sats": 21,
#   "expires_in": 600
# }`;

export default function Home() {
  const revealRef = useReveal();

  return (
    <div ref={revealRef} className="flex flex-col gap-5">
      <section className="hero-panel reveal">
        <div className="hero-content">
          <p className="eyebrow">Lightning Native API Access</p>
          <h1 className="glow-title">Pay-Per-Request APIs via the Lightning Network</h1>


          <p className="hero-sub" >
            No sign-up, No KYC. Request once, pay in sats, redeem instantly.
          </p>
          <div className="hero-callouts">
            <span className="pill pill-bitcoin">Lightning Native Billing</span>
            <span className="pill">Globally Available</span>
            <span className="pill">No Account Lock-In</span>
          </div>
          <div className="flex flex-wrap gap-3">
            <Link to="/catalog" className="btn-primary">
              Explore APIs
            </Link>
          </div>
        </div>
      </section>

      <section className="section reveal">
        <h2 className="section-title">Built For Instant Access</h2>
        <div className="grid md:grid-cols-3 gap-4">
          <GlassCard>
            <h3 className="text-lg text-[#a8e9ff] mb-2">No Account Needed</h3>
            <p className="text-[#95b9cd]">
              No signup, no API key, no credit card. Send a request, pay the invoice, get your response.
            </p>
          </GlassCard>
          <GlassCard>
            <h3 className="text-lg text-[#a8e9ff] mb-2">Pay Per Request</h3>
            <p className="text-[#95b9cd]">
              Every call is priced upfront in sats. You see exactly what it costs before you pay. No surprises.
            </p>
          </GlassCard>
          <GlassCard>
            <h3 className="text-lg text-[#a8e9ff] mb-2">Works Anywhere</h3>
            <p className="text-[#95b9cd]">
              If you can send a Lightning payment, you can use this. No country restrictions, no KYC, no waiting.
            </p>
          </GlassCard>
        </div>
      </section>

            <section className="section reveal">
        <h2 className="section-title">How It Works</h2>
        <FlowDiagram />
      </section>
    </div>
  );
}
