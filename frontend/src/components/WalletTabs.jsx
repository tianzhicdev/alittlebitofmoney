import { useState } from 'react';
import CodeTabs from './CodeTabs';

const wallets = [
  {
    id: 'phoenixd',
    label: 'Phoenixd',
    snippets: {
      python: `import requests

def pay_invoice(bolt11):
    resp = requests.post(
        "http://localhost:9740/payinvoice",
        data={"invoice": bolt11},
        auth=("", "your-phoenixd-password")
    )
    # Phoenix returns preimage directly
    return resp.json()["paymentPreimage"]`,
      javascript: `async function payInvoice(bolt11) {
  const resp = await fetch("http://localhost:9740/payinvoice", {
    method: "POST",
    headers: {
      "Authorization": "Basic " + btoa(":your-phoenixd-password"),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: \`invoice=\${bolt11}\`,
  });
  const { paymentPreimage } = await resp.json();
  return paymentPreimage;
}`,
      bash: `pay_invoice() {
  curl -s -u ":$PHOENIX_PASSWORD" \
    -d "invoice=$1" \
    http://localhost:9740/payinvoice | jq -r '.paymentPreimage'
}`,
    },
  },
  {
    id: 'lnd',
    label: 'LND',
    snippets: {
      python: `import requests, base64

def pay_invoice(bolt11):
    resp = requests.post(
        "https://localhost:8080/v1/channels/transactions",
        json={"payment_request": bolt11},
        headers={"Grpc-Metadata-macaroon": MACAROON_HEX},
        verify=False
    )
    # LND returns base64 preimage, convert to hex
    b64_preimage = resp.json()["payment_preimage"]
    return base64.b64decode(b64_preimage).hex()`,
      javascript: `async function payInvoice(bolt11) {
  const resp = await fetch("https://localhost:8080/v1/channels/transactions", {
    method: "POST",
    headers: { "Grpc-Metadata-macaroon": MACAROON_HEX },
    body: JSON.stringify({ payment_request: bolt11 }),
  });
  const { payment_preimage } = await resp.json();
  return [...atob(payment_preimage)]
    .map((char) => char.charCodeAt(0).toString(16).padStart(2, "0"))
    .join("");
}`,
    },
  },
  {
    id: 'cln',
    label: 'CLN',
    snippets: {
      python: `import subprocess, json

def pay_invoice(bolt11):
    result = subprocess.run(
        ["lightning-cli", "pay", bolt11],
        capture_output=True,
        text=True
    )
    return json.loads(result.stdout)["payment_preimage"]`,
      bash: `pay_invoice() {
  lightning-cli pay "$1" | jq -r '.payment_preimage'
}`,
    },
  },
  {
    id: 'lnbits',
    label: 'LNbits',
    snippets: {
      python: `import requests

def pay_invoice(bolt11):
    # Step 1: Pay
    resp = requests.post(
        "https://your-lnbits/api/v1/payments",
        json={"out": True, "bolt11": bolt11},
        headers={"X-Api-Key": LNBITS_ADMIN_KEY}
    )
    payment_hash = resp.json()["payment_hash"]

    # Step 2: Fetch preimage from payment details
    detail = requests.get(
        f"https://your-lnbits/api/v1/payments/{payment_hash}",
        headers={"X-Api-Key": LNBITS_ADMIN_KEY}
    )
    return detail.json()["details"]["preimage"]`,
    },
  },
  {
    id: 'alby',
    label: 'Alby',
    snippets: {
      javascript: `async function payInvoice(bolt11) {
  if (!window.webln) {
    throw new Error("Install Alby extension");
  }

  await window.webln.enable();
  const { preimage } = await window.webln.sendPayment(bolt11);
  return preimage;
}`,
      python: `import requests

def pay_invoice(bolt11):
    resp = requests.post(
        "https://api.getalby.com/payments/bolt11",
        json={"invoice": bolt11},
        headers={"Authorization": f"Bearer {ALBY_TOKEN}"}
    )
    return resp.json()["payment_preimage"]`,
    },
  },
  {
    id: 'strike',
    label: 'Strike',
    snippets: {
      python: `import requests

def pay_invoice(bolt11):
    quote = requests.post(
        "https://api.strike.me/v1/payment-quotes/lightning",
        json={"lnInvoice": bolt11, "sourceCurrency": "USD"},
        headers={"Authorization": f"Bearer {STRIKE_API_KEY}"}
    )
    quote_id = quote.json()["paymentQuoteId"]

    resp = requests.patch(
        f"https://api.strike.me/v1/payment-quotes/{quote_id}/execute",
        headers={"Authorization": f"Bearer {STRIKE_API_KEY}"}
    )
    return resp.json()["preimage"]`,
    },
  },
];

export default function WalletTabs() {
  const [activeWallet, setActiveWallet] = useState(0);
  const wallet = wallets[activeWallet] || wallets[0];
  const tabs = Object.entries(wallet.snippets).map(([language, code]) => ({
    label: language,
    language,
    code,
  }));

  return (
    <div className="reveal">
      <div className="flex flex-wrap gap-2 mb-4">
        {wallets.map((candidate, index) => (
          <button
            key={candidate.id}
            type="button"
            className={`code-tab ${index === activeWallet ? 'active' : ''}`.trim()}
            onClick={() => setActiveWallet(index)}
          >
            {candidate.label}
          </button>
        ))}
      </div>
      <CodeTabs tabs={tabs} />
    </div>
  );
}
