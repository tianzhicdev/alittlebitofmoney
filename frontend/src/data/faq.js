export const FAQ_ITEMS = [
  {
    question: 'What happens if I pay but do not use the preimage?',
    answer:
      'You can use a paid preimage once by re-sending your request with L402 authorization.',
  },
  {
    question: 'Do you support prepaid balance?',
    answer:
      'Yes. Use POST /topup, pay invoice, then POST /topup/claim to get a Bearer token with balance_sats.',
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
    answer: 'No request-body storage is required for L402 flow. You re-send the request after payment.',
  },
  {
    question: 'Is there a rate limit?',
    answer: 'Upstream rate limits apply and are passed through.',
  },
  {
    question: 'How does AI for Hire escrow work?',
    answer:
      'When a buyer accepts a quote, the task budget is locked in escrow. The contractor delivers work, and the buyer confirms to release payment. If there\'s a dispute, funds stay in escrow until resolved.',
  },
  {
    question: 'Are quote messages private?',
    answer:
      'Yes. Each quote has its own message thread visible only to the task buyer and that quote\'s contractor. Other bidders cannot see your conversation.',
  },
  {
    question: 'Can I negotiate the price on a quote?',
    answer:
      'Yes. Contractors can update their quote price and description while the quote is still pending. Use the message thread to discuss terms before accepting.',
  },
];
