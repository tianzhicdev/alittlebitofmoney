import { useState } from 'react';

export default function CodeBlock({ code, language }) {
  const [copyLabel, setCopyLabel] = useState('Copy');

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(code || '');
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
        <span>{language}</span>
        <button type="button" className="copy-btn" onClick={onCopy}>
          {copyLabel}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </article>
  );
}
