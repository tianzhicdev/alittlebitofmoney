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
          <h3>RE-SEND</h3>
          <p>
            <span className="inline-code">POST /openai/v1/... + Authorization: L402 ...</span>
            <br />
            Returns the upstream API response.
          </p>
        </GlassCard>
      </div>

      {detailed ? (
        <div className="preimage-callout">
          <strong>What&apos;s a preimage?</strong> When you pay a Lightning invoice, the network reveals
          the preimage: a 64-character hex string. Re-send your original request with
          <span className="inline-code"> Authorization: L402 {'<macaroon>:<preimage>'}</span>.
        </div>
      ) : null}
    </div>
  );
}
