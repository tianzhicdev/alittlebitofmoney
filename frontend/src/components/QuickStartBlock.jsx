import { useState } from 'react';

const PLAIN = `# 1. Send request, get a Lightning invoice
INVOICE=$(curl -sS -X POST https://alittlebitofmoney.com/openai/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-4o-mini","messages":[{"role":"user","content":"hello bitcoin world"}]}' | jq -r '.invoice')

# 2. Pay the invoice (example: phoenixd wallet)
PREIMAGE=$(curl -sS -X POST http://localhost:9741/payinvoice \\
  -u ":$PHOENIX_WALLET_PASSWORD" \\
  -d "invoice=$INVOICE" | jq -r '.paymentPreimage')

# 3. Redeem with preimage
curl -sS "https://alittlebitofmoney.com/redeem?preimage=$PREIMAGE" | jq -r '.choices[0].message.content'`;

export default function QuickStartBlock() {
  const [copyLabel, setCopyLabel] = useState('Copy');

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(PLAIN);
      setCopyLabel('Copied');
    } catch {
      setCopyLabel('Copy failed');
    } finally {
      window.setTimeout(() => setCopyLabel('Copy'), 1200);
    }
  }

  return (
    <article className="code-card">
      <div className="code-head">
        <span>bash</span>
        <button type="button" className="copy-btn" onClick={onCopy}>
          {copyLabel}
        </button>
      </div>
      <pre>
        <code>
          <span className="qs-comment">{'# 1. Send request, get a Lightning invoice'}</span>{'\n'}
          <span className="qs-var">INVOICE</span>{'=$('}<span className="qs-cmd">curl</span>{' -sS -X POST '}<span className="qs-url">https://alittlebitofmoney.com/openai/v1/chat/completions</span>{' \\\n'}
          {'  -H '}<span className="qs-str">{'"Content-Type: application/json"'}</span>{' \\\n'}
          {'  -d '}<span className="qs-str">{"'{\"model\":\"gpt-4o-mini\",\"messages\":[{\"role\":\"user\",\"content\":\"hello bitcoin world\"}]}'"}</span>{' | '}<span className="qs-cmd">jq</span>{" -r '.invoice')\n"}
          {'\n'}
          <span className="qs-comment">{'# 2. Pay the invoice (example: phoenixd wallet)'}</span>{'\n'}
          <span className="qs-var">PREIMAGE</span>{'=$('}<span className="qs-cmd">curl</span>{' -sS -X POST '}<span className="qs-url">http://localhost:9741/payinvoice</span>{' \\\n'}
          {'  -u '}<span className="qs-str">{'":'}<span className="qs-var">$PHOENIX_WALLET_PASSWORD</span>{'"'}</span>{' \\\n'}
          {'  -d '}<span className="qs-str">{'"invoice='}<span className="qs-var">$INVOICE</span>{'"'}</span>{" | "}<span className="qs-cmd">jq</span>{" -r '.paymentPreimage')\n"}
          {'\n'}
          <span className="qs-comment">{'# 3. Redeem with preimage'}</span>{'\n'}
          <span className="qs-cmd">curl</span>{' -sS '}<span className="qs-str">{'"'}<span className="qs-url">https://alittlebitofmoney.com/redeem</span>{'?preimage='}<span className="qs-var">$PREIMAGE</span>{'"'}</span>{' | '}<span className="qs-cmd">jq</span>{" -r '.choices[0].message.content'\n"}
          <span className="qs-output">Hello! How can I assist you in the Bitcoin world today?</span>
        </code>
      </pre>
    </article>
  );
}
