import GlassCard from './GlassCard';

export default function FlowDiagram({ detailed = false }) {
  return (
    <div className="reveal">
      <div className="flow-grid">
        <GlassCard className="flow-step">
          <span className="step-number">1</span>
          <h3>REQUEST</h3>
          <p>
            <span className="inline-code">POST /openai/v1/...</span>
            <br />
            Returns 402 with invoice and payment hash.
          </p>
        </GlassCard>
        <div className="flow-arrow" aria-hidden>
          -&gt;
        </div>
        <GlassCard className="flow-step">
          <span className="step-number">2</span>
          <h3>PAY</h3>
          <p>
            Pay the BOLT11 invoice with any Lightning wallet.
            <br />
            Your wallet reveals a preimage.
          </p>
        </GlassCard>
        <div className="flow-arrow" aria-hidden>
          -&gt;
        </div>
        <GlassCard className="flow-step">
          <span className="step-number">3</span>
          <h3>REDEEM</h3>
          <p>
            <span className="inline-code">GET /redeem?preimage=...</span>
            <br />
            Returns the upstream API response.
          </p>
        </GlassCard>
      </div>

      {detailed ? (
        <div className="preimage-callout">
          <strong>What&apos;s a preimage?</strong> When
          you pay a Lightning invoice, the network reveals the preimage: a 64-character hex string. Send it to us. No accounts and no API keys: the preimage is the
          receipt.
        </div>
      ) : null}
    </div>
  );
}
