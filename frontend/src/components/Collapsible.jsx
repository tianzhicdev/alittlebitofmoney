import { useState } from 'react';

export default function Collapsible({ title, children, defaultOpen = false }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className="collapsible">
      <button
        type="button"
        className="collapsible-header"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
      >
        <span className="collapsible-icon">{isOpen ? '▼' : '▶'}</span>
        <span className="collapsible-title">{title}</span>
      </button>
      {isOpen && <div className="collapsible-content">{children}</div>}
    </div>
  );
}
